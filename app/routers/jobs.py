import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Image, JobStatus, SegmentationJob, Team
from app.schemas.jobs import JobCreate, JobResponse
from app.security import get_current_team

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: JobCreate,
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
        params["seed"] = secrets.randbelow(2**32)

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

    return JobResponse.model_validate(job)
