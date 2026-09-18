import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import JobStatus


class _BaseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int = Field(ge=2, le=16)
    max_iters: int = Field(ge=1, le=1000)
    seed: int | None = Field(default=None, ge=0, lt=2**31)


class KmeansParams(_BaseParams):
    algorithm: Literal["kmeans"]


class PfcmParams(_BaseParams):
    algorithm: Literal["pfcm"]
    m: float = Field(gt=1)
    eta: float = Field(gt=1)


JobParams = Annotated[KmeansParams | PfcmParams, Field(discriminator="algorithm")]


class JobCreate(BaseModel):
    image_id: uuid.UUID
    params: JobParams


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    image_id: uuid.UUID
    status: JobStatus
    params: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
