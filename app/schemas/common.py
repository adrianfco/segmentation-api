from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class SignedUrlResponse(BaseModel):
    url: HttpUrl
    expires_at: datetime


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
