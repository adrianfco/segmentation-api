import uuid
from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JobStatus(StrEnum):
    queued = auto()
    running = auto()
    succeeded = auto()
    failed = auto()


class SegmentationJob(Base):
    __tablename__ = "segmentation_jobs"
    __table_args__ = (Index("ix_segmentation_jobs_team_id_status", "team_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, create_constraint=True, length=20),
        default=JobStatus.queued,
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result_path: Mapped[str | None] = mapped_column(String(500), default=None)
    error_message: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
