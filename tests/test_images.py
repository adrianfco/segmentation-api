import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Image, Team
from app.security import get_current_team
from app.storage import StorageError, get_storage

PNG = b"\x89PNG\r\n\x1a\n" + b"rest-of-image"


def make_client(session, storage, team=None):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pw@localhost:5432/postgres",
        supabase_url="https://example.supabase.co/",
        supabase_service_role_key="service-role-key",
        max_upload_size_mb=1,
    )
    if team is not None:
        app.dependency_overrides[get_current_team] = lambda: team
    return TestClient(app)


def make_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.refresh.side_effect = lambda image: setattr(image, "created_at", datetime.now(UTC))
    return session


def make_team():
    return Team(id=uuid.uuid4(), name="Acme")


def test_upload_png_returns_201():
    team, session, storage = make_team(), make_session(), AsyncMock()

    with make_client(session, storage, team) as client:
        response = client.post("/v1/images", files={"file": ("cat.png", PNG, "image/png")})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "filename", "created_at"}
    assert body["filename"] == "cat.png"

    [image] = session.add.call_args.args
    assert isinstance(image, Image)
    assert str(image.id) == body["id"]
    assert image.team_id == team.id
    assert image.storage_path == f"{team.id}/images/{image.id}.png"
    storage.upload.assert_awaited_once_with(image.storage_path, PNG, "image/png")
    session.commit.assert_awaited_once()


def test_upload_non_png_returns_415():
    session, storage = make_session(), AsyncMock()

    with make_client(session, storage, make_team()) as client:
        response = client.post(
            "/v1/images", files={"file": ("cat.jpg", b"\xff\xd8\xff\xe0", "image/png")}
        )

    assert response.status_code == 415
    storage.upload.assert_not_awaited()
    session.add.assert_not_called()


def test_upload_too_large_returns_413():
    session, storage = make_session(), AsyncMock()
    data = PNG + b"\x00" * 1024 * 1024

    with make_client(session, storage, make_team()) as client:
        response = client.post("/v1/images", files={"file": ("big.png", data, "image/png")})

    assert response.status_code == 413
    storage.upload.assert_not_awaited()
    session.add.assert_not_called()


def test_upload_storage_failure_returns_502():
    session, storage = make_session(), AsyncMock()
    storage.upload.side_effect = StorageError("Storage returned 500", 500)

    with make_client(session, storage, make_team()) as client:
        response = client.post("/v1/images", files={"file": ("cat.png", PNG, "image/png")})

    assert response.status_code == 502
    session.add.assert_not_called()


def test_upload_without_file_returns_422():
    with make_client(make_session(), AsyncMock(), make_team()) as client:
        response = client.post("/v1/images")

    assert response.status_code == 422


def test_upload_without_api_key_returns_401():
    session, storage = make_session(), AsyncMock()

    with make_client(session, storage) as client:
        response = client.post("/v1/images", files={"file": ("cat.png", PNG, "image/png")})

    assert response.status_code == 401
    storage.upload.assert_not_awaited()
