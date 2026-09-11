import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import storage
from app.config import get_settings
from app.storage import StorageClient, StorageError

BASE_URL = "https://example.supabase.co/storage/v1/"
SERVICE_KEY = "service-key-that-must-not-leak"

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+psycopg://user:pw@localhost:5432/postgres",
    "SUPABASE_URL": "https://example.supabase.co/",
    "SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY,
    "SUPABASE_STORAGE_BUCKET": "segmentation-test",
}


def make_client(handler):
    http = httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"apikey": SERVICE_KEY},
        transport=httpx.MockTransport(handler),
    )
    return StorageClient(http, "segmentation")


async def test_upload_sends_file_to_bucket_path():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"Key": "segmentation/team/img.png"})

    await make_client(handler).upload("team/img.png", b"\x89PNG", "image/png")

    [request] = requests
    assert request.method == "POST"
    assert request.url == f"{BASE_URL}object/segmentation/team/img.png"
    assert request.content == b"\x89PNG"
    assert request.headers["content-type"] == "image/png"
    assert request.headers["x-upsert"] == "false"


async def test_upload_duplicate_raises_409():
    client = make_client(
        lambda request: httpx.Response(400, json={"statusCode": "409", "error": "Duplicate"})
    )

    with pytest.raises(StorageError) as exc_info:
        await client.upload("team/img.png", b"\x89PNG", "image/png")

    assert exc_info.value.status_code == 409


async def test_create_signed_url_returns_absolute_url():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"signedURL": "/object/sign/segmentation/team/img.png?token=abc"}
        )

    before = datetime.now(UTC)
    signed = await make_client(handler).create_signed_url("team/img.png", expires_in=60)
    after = datetime.now(UTC)

    [request] = requests
    assert request.url == f"{BASE_URL}object/sign/segmentation/team/img.png"
    assert json.loads(request.content) == {"expiresIn": 60}
    assert str(signed.url) == f"{BASE_URL}object/sign/segmentation/team/img.png?token=abc"
    assert before + timedelta(seconds=60) <= signed.expires_at <= after + timedelta(seconds=60)


async def test_create_signed_url_missing_object_raises_404():
    client = make_client(
        lambda request: httpx.Response(400, json={"statusCode": "404", "error": "not_found"})
    )

    with pytest.raises(StorageError) as exc_info:
        await client.create_signed_url("team/missing.png", expires_in=60)

    assert exc_info.value.status_code == 404


async def test_create_signed_url_unexpected_response_raises():
    client = make_client(lambda request: httpx.Response(200, json={}))

    with pytest.raises(StorageError):
        await client.create_signed_url("team/img.png", expires_in=60)


async def test_error_without_status_in_body_uses_http_status():
    client = make_client(lambda request: httpx.Response(502, text="Bad Gateway"))

    with pytest.raises(StorageError) as exc_info:
        await client.upload("team/img.png", b"\x89PNG", "image/png")

    assert exc_info.value.status_code == 502


async def test_connection_error_raises_storage_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(StorageError) as exc_info:
        await make_client(handler).upload("team/img.png", b"\x89PNG", "image/png")

    assert exc_info.value.status_code is None


async def test_error_message_does_not_include_service_key():
    client = make_client(lambda request: httpx.Response(500, text="internal error"))

    with pytest.raises(StorageError) as exc_info:
        await client.upload("team/img.png", b"\x89PNG", "image/png")

    assert SERVICE_KEY not in str(exc_info.value)


@pytest.fixture
def configured_env(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    caches = (get_settings, storage.get_storage)
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


def test_get_storage_uses_settings_and_is_cached(configured_env):
    client = storage.get_storage()

    assert client is storage.get_storage()
    assert client._bucket == "segmentation-test"
    assert client._http.base_url == BASE_URL
    assert client._http.headers["apikey"] == SERVICE_KEY
    assert "authorization" not in client._http.headers
