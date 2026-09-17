import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobStatus, SegmentationJob


class JobQueue(Protocol):
    async def claim(self) -> SegmentationJob | None: ...

    async def complete(self, job_id: uuid.UUID, result_path: str) -> None: ...

    async def fail(self, job_id: uuid.UUID, error_message: str) -> None: ...


class PostgresJobQueue:
    def __init__(self, session: AsyncSession, lease_seconds: int, max_attempts: int) -> None:
        self._session = session
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def claim(self) -> SegmentationJob | None:
        now = datetime.now(UTC)
        stmt = (
            select(SegmentationJob)
            .where(
                or_(
                    SegmentationJob.status == JobStatus.queued,
                    and_(
                        SegmentationJob.status == JobStatus.running,
                        SegmentationJob.lease_expires_at < now,
                    ),
                )
            )
            .order_by(SegmentationJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = await self._session.scalar(stmt)
        if job is None:
            return None

        if job.status is JobStatus.running and job.attempts >= self._max_attempts:
            job.status = JobStatus.failed
            job.error_message = "Exceeded max attempts after lease expiry"
            job.lease_expires_at = None
            await self._session.commit()
            return None

        job.status = JobStatus.running
        job.attempts += 1
        job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def complete(self, job_id: uuid.UUID, result_path: str) -> None:
        # A worker whose lease already expired and was reclaimed elsewhere must not
        # resurrect or overwrite a job another worker now owns.
        await self._session.execute(
            update(SegmentationJob)
            .where(SegmentationJob.id == job_id, SegmentationJob.status == JobStatus.running)
            .values(status=JobStatus.succeeded, result_path=result_path, lease_expires_at=None)
        )
        await self._session.commit()

    async def fail(self, job_id: uuid.UUID, error_message: str) -> None:
        await self._session.execute(
            update(SegmentationJob)
            .where(SegmentationJob.id == job_id, SegmentationJob.status == JobStatus.running)
            .values(status=JobStatus.failed, error_message=error_message, lease_expires_at=None)
        )
        await self._session.commit()
