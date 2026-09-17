from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from app.models import Base


@pytest.fixture(scope="session")
def postgres_container() -> AsyncGenerator[PostgresContainer, None]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
async def test_engine(postgres_container: PostgresContainer) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(postgres_container.get_connection_url())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    # Wrap each test in a transaction rolled back afterward, so a session.commit()
    # inside the test doesn't leak rows into the next one.
    async with test_engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        yield session
        await session.close()
        await transaction.rollback()
