import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    created_at: datetime
