import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.security import get_current_team
from app.core.storage import StorageClient, StorageError, get_storage
from app.models import Image, JobStatus, SegmentationJob, Team
from app.schemas.common import Page, PaginationParams, SignedUrlResponse
from app.schemas.jobs import JobCreate, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: JobCreate,
    request: Request,
    response: Response,
    team: Team = Depends(get_current_team),
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    image = await session.scalar(
        select(Image).where(Image.id == payload.image_id, Image.team_id == team.id)
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    params = payload.params.model_dump(exclude_none=True)
    if payload.params.seed is None:
        params["seed"] = secrets.randbelow(2**31)

    job = SegmentationJob(
        id=uuid.uuid4(),
        team_id=team.id,
        image_id=image.id,
        status=JobStatus.queued,
        params=params,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    response.headers["Location"] = str(request.url_for("get_job", job_id=job.id))

    return JobResponse.model_validate(job)


@router.get("", response_model=Page[JobResponse])
async def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    image_id: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    team: Team = Depends(get_current_team),
    session: AsyncSession = Depends(get_session),
) -> Page[JobResponse]:
    filters = [SegmentationJob.team_id == team.id]
    if status_filter is not None:
        filters.append(SegmentationJob.status == status_filter)
    if image_id is not None:
        filters.append(SegmentationJob.image_id == image_id)

    total = await session.scalar(select(func.count()).select_from(SegmentationJob).where(*filters))
    jobs = await session.scalars(
        select(SegmentationJob)
        .where(*filters)
        .order_by(SegmentationJob.created_at.desc(), SegmentationJob.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )

    return Page[JobResponse](
        items=jobs.all(), total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    team: Team = Depends(get_current_team),
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    job = await session.scalar(
        select(SegmentationJob).where(
            SegmentationJob.id == job_id, SegmentationJob.team_id == team.id
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobResponse.model_validate(job)


@router.get("/{job_id}/result-url", response_model=SignedUrlResponse)
async def get_job_result_url(
    job_id: uuid.UUID,
    team: Team = Depends(get_current_team),
    session: AsyncSession = Depends(get_session),
    storage: StorageClient = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> SignedUrlResponse:
    job = await session.scalar(
        select(SegmentationJob).where(
            SegmentationJob.id == job_id, SegmentationJob.team_id == team.id
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status is not JobStatus.succeeded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Job status is {job.status}"
        )

    try:
        return await storage.create_signed_url(job.result_path, settings.signed_url_expires_seconds)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
        ) from exc
