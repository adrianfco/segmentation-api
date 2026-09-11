import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Image, Team
from app.schemas.images import ImageResponse
from app.security import get_current_team
from app.storage import StorageClient, StorageError, get_storage

router = APIRouter(prefix="/images", tags=["images"])


@router.post("", response_model=ImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile,
    team: Team = Depends(get_current_team),
    session: AsyncSession = Depends(get_session),
    storage: StorageClient = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ImageResponse:
    data = await file.read(settings.max_upload_size_bytes + 1)
    if len(data) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image exceeds {settings.max_upload_size_mb} MB",
        )
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PNG images are supported",
        )

    image_id = uuid.uuid4()
    storage_path = f"{team.id}/images/{image_id}.png"
    try:
        await storage.upload(storage_path, data, "image/png")
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
        ) from exc

    image = Image(
        id=image_id,
        team_id=team.id,
        filename=(file.filename or "")[:255],
        storage_path=storage_path,
    )
    session.add(image)
    await session.commit()
    await session.refresh(image)

    return ImageResponse.model_validate(image)
