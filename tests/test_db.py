import pytest
from sqlalchemy import text

from app.core import db
from app.core.config import get_settings

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+psycopg://user:pw-that-must-not-leak@localhost:5432/postgres",
    "SUPABASE_URL": "https://example.supabase.co/",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
}


@pytest.fixture
def configured_env(monkeypatch):
    """Provide required settings and reset every lazy cache around the test.

    Building an async engine does not open a connection, so these stay hermetic.
    """
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    caches = (get_settings, db.get_engine, db.get_sessionmaker)
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


def test_engine_is_built_from_settings_and_cached(configured_env):
    engine = db.get_engine()

    assert engine is db.get_engine()
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.get_driver_name() == "psycopg"
    assert engine.url.database == "postgres"


def test_sessionmaker_is_bound_to_the_engine_and_cached(configured_env):
    sessionmaker = db.get_sessionmaker()

    assert sessionmaker is db.get_sessionmaker()
    assert sessionmaker.kw["bind"] is db.get_engine()
    assert sessionmaker.kw["expire_on_commit"] is False


async def test_engine_replaces_connection_closed_by_server(
    configured_env, monkeypatch, postgres_container, test_engine
):
    monkeypatch.setenv("DATABASE_URL", postgres_container.get_connection_url())
    engine = db.get_engine()

    async with engine.connect() as conn:
        pid = await conn.scalar(text("SELECT pg_backend_pid()"))
    async with test_engine.connect() as conn:
        await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT 1")) == 1

    await engine.dispose()
