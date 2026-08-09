import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import ApiKey, Team


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_current_team(
    x_api_key: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> Team:
    key_hash = hash_api_key(x_api_key)
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    team = await session.get(Team, api_key.team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return team
