import asyncio
import contextlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

import app.worker as worker
from app.core.queue import PostgresJobQueue
from app.core.storage import StorageClient
from app.models import Image, JobStatus, SegmentationJob, Team

BASE_URL = "https://example.supabase.co/storage/v1/"


def test_segment_kwargs_kmeans():
    params = {"algorithm": "kmeans", "k": 4, "seed": 1, "max_iters": 100}

    assert worker._segment_kwargs(params) == params


def test_segment_kwargs_pfcm():
    params = {"algorithm": "pfcm", "k": 4, "seed": 1, "max_iters": 100, "m": 2.0, "eta": 3.0}

    kwargs = worker._segment_kwargs(params)

    assert kwargs["pfcm_m"] == 2.0
    assert kwargs["pfcm_eta"] == 3.0
    assert "m" not in kwargs
    assert "eta" not in kwargs


def make_storage(handler) -> StorageClient:
    http = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return StorageClient(http, "segmentation")


async def seed_job(session: AsyncSession, *, params: dict) -> SegmentationJob:
    team = Team(name=f"team-{uuid.uuid4()}")
    session.add(team)
    await session.flush()
    image = Image(team_id=team.id, filename="cat.png", storage_path=f"{team.id}/cat.png")
    session.add(image)
    await session.flush()

    job = SegmentationJob(
        team_id=team.id, image_id=image.id, status=JobStatus.running, attempts=1, params=params
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def run_process_job(job, session, storage) -> None:
    queue = PostgresJobQueue(session, lease_seconds=300, max_attempts=3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        await worker._process_job(job, session, storage, queue, pool, asyncio.get_running_loop())


async def test_process_job_succeeded_path(db_session, monkeypatch):
    job = await seed_job(
        db_session, params={"algorithm": "kmeans", "k": 2, "seed": 1, "max_iters": 10}
    )

    def fake_segment_image(input_path, output_path, **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"segmented-png-bytes")
        return SimpleNamespace(success=True, error_message=None)

    monkeypatch.setattr(worker, "segment_image", fake_segment_image)

    job_id, team_id = job.id, job.team_id
    uploads = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, content=b"\x89PNG-source")
        uploads.append(request)
        return httpx.Response(200, json={"Key": "ok"})

    await run_process_job(job, db_session, make_storage(handler))

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.status == JobStatus.succeeded
    assert refreshed.result_path == f"{team_id}/results/{job_id}.png"
    [upload] = uploads
    assert upload.url == f"{BASE_URL}object/segmentation/{refreshed.result_path}"
    assert upload.content == b"segmented-png-bytes"
    assert upload.headers["x-upsert"] == "true"


async def test_process_job_failed_when_segmentation_reports_failure(db_session, monkeypatch):
    job = await seed_job(
        db_session, params={"algorithm": "kmeans", "k": 2, "seed": 1, "max_iters": 10}
    )

    monkeypatch.setattr(
        worker,
        "segment_image",
        lambda input_path, output_path, **kwargs: SimpleNamespace(
            success=False, error_message="boom"
        ),
    )
    job_id = job.id
    storage = make_storage(lambda request: httpx.Response(200, content=b"\x89PNG-source"))
    await run_process_job(job, db_session, storage)

    refreshed = await db_session.get(SegmentationJob, job_id)
    assert refreshed.status == JobStatus.failed
    assert refreshed.error_message == "boom"


async def test_worker_loop_survives_claim_error(monkeypatch):
    recovered = asyncio.Event()
    claims = 0

    class FlakyQueue:
        def __init__(self, *args):
            pass

        async def claim(self):
            nonlocal claims
            claims += 1
            if claims == 1:
                raise OperationalError("SELECT", {}, Exception("server closed the connection"))
            recovered.set()

    monkeypatch.setattr(worker, "PostgresJobQueue", FlakyQueue)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: contextlib.nullcontext)
    monkeypatch.setattr(worker, "get_storage", lambda: None)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(
            job_lease_seconds=300, job_max_attempts=3, worker_idle_poll_seconds=0
        ),
    )

    task = asyncio.create_task(worker._worker_loop(0, None))
    try:
        await asyncio.wait_for(recovered.wait(), timeout=1)
    finally:
        task.cancel()
