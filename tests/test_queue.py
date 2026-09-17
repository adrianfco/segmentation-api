import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.queue import PostgresJobQueue
from app.models import Image, JobStatus, SegmentationJob, Team

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3


def make_queue(session: AsyncSession) -> PostgresJobQueue:
    return PostgresJobQueue(session, lease_seconds=LEASE_SECONDS, max_attempts=MAX_ATTEMPTS)


async def seed_job(
    session: AsyncSession,
    *,
    status: JobStatus = JobStatus.queued,
    attempts: int = 0,
    lease_expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> SegmentationJob:
    team = Team(name=f"team-{uuid.uuid4()}")
    session.add(team)
    await session.flush()
    image = Image(team_id=team.id, filename="cat.png", storage_path=f"{team.id}/cat.png")
    session.add(image)
    await session.flush()
    job = SegmentationJob(
        team_id=team.id,
        image_id=image.id,
        status=status,
        params={},
        attempts=attempts,
        lease_expires_at=lease_expires_at,
    )
    if created_at is not None:
        job.created_at = created_at
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def test_claim_returns_oldest_queued_job_first(db_session):
    now = datetime.now(UTC)
    older = await seed_job(db_session, created_at=now - timedelta(minutes=5))
    await seed_job(db_session, created_at=now)

    claimed = await make_queue(db_session).claim()

    assert claimed.id == older.id
    assert claimed.status == JobStatus.running
    assert claimed.attempts == 1
    assert claimed.lease_expires_at is not None


async def test_claim_returns_none_when_nothing_claimable(db_session):
    assert await make_queue(db_session).claim() is None


async def test_claim_ignores_job_with_active_lease(db_session):
    await seed_job(
        db_session,
        status=JobStatus.running,
        attempts=1,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    assert await make_queue(db_session).claim() is None


async def test_claim_reclaims_expired_lease_job(db_session):
    job = await seed_job(
        db_session,
        status=JobStatus.running,
        attempts=1,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    claimed = await make_queue(db_session).claim()

    assert claimed.id == job.id
    assert claimed.attempts == 2
    assert claimed.lease_expires_at > datetime.now(UTC)


async def test_claim_fails_job_that_exhausted_max_attempts_on_expired_lease(db_session):
    job = await seed_job(
        db_session,
        status=JobStatus.running,
        attempts=MAX_ATTEMPTS,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    job_id = job.id

    assert await make_queue(db_session).claim() is None

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.status == JobStatus.failed
    assert refreshed.error_message is not None
    assert refreshed.lease_expires_at is None


async def test_claim_concurrent_workers_never_claim_the_same_job(test_engine: AsyncEngine):
    async with AsyncSession(bind=test_engine) as setup_session:
        job = await seed_job(setup_session)
        team_id = job.team_id

    session_a = AsyncSession(bind=test_engine)
    session_b = AsyncSession(bind=test_engine)
    try:
        claimed_a, claimed_b = await asyncio.gather(
            make_queue(session_a).claim(), make_queue(session_b).claim()
        )
    finally:
        await session_a.close()
        await session_b.close()
        async with AsyncSession(bind=test_engine) as cleanup_session:
            await cleanup_session.execute(delete(Team).where(Team.id == team_id))
            await cleanup_session.commit()

    claimed = [j for j in (claimed_a, claimed_b) if j is not None]
    assert len(claimed) == 1
    assert claimed[0].id == job.id


async def test_complete_marks_job_succeeded(db_session):
    job = await seed_job(db_session, status=JobStatus.running, attempts=1)
    job_id = job.id

    await make_queue(db_session).complete(job_id, "team/results/job.png")

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.status == JobStatus.succeeded
    assert refreshed.result_path == "team/results/job.png"
    assert refreshed.lease_expires_at is None


async def test_complete_is_a_noop_when_job_is_not_running(db_session):
    job = await seed_job(db_session, status=JobStatus.succeeded, attempts=1)
    job_id = job.id

    await make_queue(db_session).complete(job_id, "team/results/job.png")

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.result_path is None


async def test_fail_marks_job_failed(db_session):
    job = await seed_job(db_session, status=JobStatus.running, attempts=1)
    job_id = job.id

    await make_queue(db_session).fail(job_id, "boom")

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.status == JobStatus.failed
    assert refreshed.error_message == "boom"
    assert refreshed.lease_expires_at is None


async def test_fail_is_a_noop_when_job_is_not_running(db_session):
    job = await seed_job(db_session, status=JobStatus.queued, attempts=0)
    job_id = job.id

    await make_queue(db_session).fail(job_id, "boom")

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.error_message is None
