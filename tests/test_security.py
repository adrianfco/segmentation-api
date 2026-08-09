import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models import ApiKey, Team
from app.security import generate_api_key, get_current_team, hash_api_key


def test_generate_api_key_returns_unique_high_entropy_values():
    first, second = generate_api_key(), generate_api_key()

    assert first != second
    assert len(first) >= 32


def test_hash_api_key_is_deterministic():
    raw_key = generate_api_key()

    assert hash_api_key(raw_key) == hash_api_key(raw_key)


def test_hash_api_key_differs_for_different_keys():
    assert hash_api_key(generate_api_key()) != hash_api_key(generate_api_key())


@pytest.fixture
def session():
    return AsyncMock()


async def test_get_current_team_returns_team_for_valid_key(session):
    team_id = uuid.uuid4()
    session.scalar.return_value = ApiKey(
        id=uuid.uuid4(), team_id=team_id, name="ci", key_hash=hash_api_key("valid-key")
    )
    session.get.return_value = Team(id=team_id, name="Acme", created_at=datetime.now(UTC))

    team = await get_current_team(x_api_key="valid-key", session=session)

    assert team.id == team_id


async def test_get_current_team_rejects_unknown_key(session):
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_current_team(x_api_key="bogus-key", session=session)

    assert exc_info.value.status_code == 401


async def test_get_current_team_rejects_key_whose_team_was_deleted(session):
    session.scalar.return_value = ApiKey(
        id=uuid.uuid4(), team_id=uuid.uuid4(), name="ci", key_hash=hash_api_key("valid-key")
    )
    session.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_current_team(x_api_key="valid-key", session=session)

    assert exc_info.value.status_code == 401
