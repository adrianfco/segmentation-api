import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.main import create_app
from app.models import Team


def _override_session(session: AsyncMock):
    async def _get_session() -> AsyncGenerator[AsyncMock, None]:
        yield session

    return _get_session


@pytest.fixture
def session():
    mock_session = AsyncMock()
    mock_session.add = Mock()
    return mock_session


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = _override_session(session)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_team_returns_201_with_the_created_team(client, session):
    async def fake_refresh(team, *args, **kwargs):
        team.id = uuid.uuid4()
        team.created_at = datetime.now(UTC)

    session.refresh.side_effect = fake_refresh

    response = client.post("/teams", json={"name": "Acme"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme"
    assert uuid.UUID(body["id"])
    assert body["created_at"]


def test_create_team_with_duplicate_name_returns_409(client, session):
    session.commit.side_effect = IntegrityError("INSERT", {}, Exception("duplicate key"))

    response = client.post("/teams", json={"name": "Acme"})

    assert response.status_code == 409
    session.rollback.assert_awaited_once()


def test_get_team_returns_200_when_found(client, session):
    team_id = uuid.uuid4()
    session.get.return_value = Team(id=team_id, name="Acme", created_at=datetime.now(UTC))

    response = client.get(f"/teams/{team_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(team_id)


def test_get_team_returns_404_when_missing(client, session):
    session.get.return_value = None

    response = client.get(f"/teams/{uuid.uuid4()}")

    assert response.status_code == 404


def test_teams_endpoints_are_documented_in_openapi(client):
    schema = client.get("/openapi.json").json()

    assert "/teams" in schema["paths"]
    assert "/teams/{team_id}" in schema["paths"]
