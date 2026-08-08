from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Build async engine lazily."""
    return create_async_engine(get_settings().database_url_str)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the lazy engine."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session."""
    async with get_sessionmaker()() as session:
        yield session
