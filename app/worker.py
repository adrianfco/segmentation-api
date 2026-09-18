import asyncio
import logging
import tempfile
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from segmentation_core import segment_image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.queue import JobQueue, PostgresJobQueue
from app.core.storage import StorageClient, get_storage
from app.models import Image, SegmentationJob

logger = logging.getLogger(__name__)


def _run_segmentation(
    input_path: str, output_path: str, **kwargs: object
) -> tuple[bool, str | None]:
    # segment_image is a pybind11 binding: neither it nor its SegmentationResult
    # return value can be pickled across a ProcessPoolExecutor boundary, so this
    # plain function (picklable by reference) does the call and hands back only
    # the plain values _process_job needs.
    result = segment_image(input_path, output_path, **kwargs)
    return result.success, result.error_message


def _segment_kwargs(params: dict) -> dict:
    kwargs = {
        "algorithm": params["algorithm"],
        "k": params["k"],
        "seed": params["seed"],
        "max_iters": params["max_iters"],
    }
    if params["algorithm"] == "pfcm":
        kwargs["pfcm_m"] = params["m"]
        kwargs["pfcm_eta"] = params["eta"]
    return kwargs


async def _process_job(
    job: SegmentationJob,
    session: AsyncSession,
    storage: StorageClient,
    queue: JobQueue,
    pool: ProcessPoolExecutor,
    loop: asyncio.AbstractEventLoop,
) -> None:
    image = await session.scalar(select(Image).where(Image.id == job.image_id))

    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / "input.png"
        output_path = Path(tmp) / "output.png"
        input_path.write_bytes(await storage.download(image.storage_path))

        success, error_message = await loop.run_in_executor(
            pool,
            partial(
                _run_segmentation, str(input_path), str(output_path), **_segment_kwargs(job.params)
            ),
        )
        if not success:
            await queue.fail(job.id, error_message or "Segmentation failed")
            return

        result_path = f"{job.team_id}/results/{job.id}.png"
        await storage.upload(result_path, output_path.read_bytes(), "image/png")
        await queue.complete(job.id, result_path)


async def _worker_loop(worker_id: int, pool: ProcessPoolExecutor) -> None:
    settings = get_settings()
    storage = get_storage()
    loop = asyncio.get_running_loop()

    while True:
        async with get_sessionmaker()() as session:
            queue = PostgresJobQueue(session, settings.job_lease_seconds, settings.job_max_attempts)
            job = await queue.claim()
            if job is None:
                await asyncio.sleep(settings.worker_idle_poll_seconds)
                continue

            logger.info("worker %d claimed job %s", worker_id, job.id)
            try:
                await _process_job(job, session, storage, queue, pool, loop)
            except Exception:
                logger.exception("worker %d failed job %s", worker_id, job.id)
                await queue.fail(job.id, "Unexpected worker error")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    with ProcessPoolExecutor(max_workers=settings.worker_concurrency) as pool:
        await asyncio.gather(*(_worker_loop(i, pool) for i in range(settings.worker_concurrency)))


if __name__ == "__main__":
    asyncio.run(main())
