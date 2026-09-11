from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.common import SignedUrlResponse


class StorageError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StorageClient:
    def __init__(self, http: httpx.AsyncClient, bucket: str) -> None:
        self._http = http
        self._bucket = bucket

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        await self._request(
            "POST",
            f"object/{self._bucket}/{path}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )

    async def create_signed_url(self, path: str, expires_in: int) -> SignedUrlResponse:
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        response = await self._request(
            "POST", f"object/sign/{self._bucket}/{path}", json={"expiresIn": expires_in}
        )

        try:
            signed_path = response.json()["signedURL"]
        except (ValueError, KeyError) as exc:
            raise StorageError("Unexpected signed URL response") from exc

        return SignedUrlResponse(
            url=f"{self._http.base_url}{signed_path.lstrip('/')}", expires_at=expires_at
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise StorageError(f"Storage request failed: {type(exc).__name__}") from exc

        if response.is_error:
            # Supabase answers most errors with 400 and puts the real status in the body
            try:
                status_code = int(response.json()["statusCode"])
            except (ValueError, KeyError, TypeError):
                status_code = response.status_code
            raise StorageError(f"Storage returned {status_code} for {method} {url}", status_code)

        return response


@lru_cache
def get_storage() -> StorageClient:
    settings = get_settings()
    key = settings.supabase_service_role_key.get_secret_value()
    http = httpx.AsyncClient(
        base_url=f"{str(settings.supabase_url).rstrip('/')}/storage/v1/",
        headers={"apikey": key},
        timeout=30,
    )
    return StorageClient(http, settings.supabase_storage_bucket)
