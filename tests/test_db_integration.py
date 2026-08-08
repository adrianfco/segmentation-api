import asyncio

import pytest
from sqlalchemy import select

from app import db
from app.models import Base, Team

pytestmark = pytest.mark.integration


def test_team_round_trips_through_postgres():
    """Smoke-test the real async stack: create schema, insert a Team, read it back.

    Requires a reachable DATABASE_URL; excluded from the default suite by the marker.
    """

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with db.get_sessionmaker()() as session:
                team = Team(name="Acme", slug="acme")
                session.add(team)
                await session.commit()

                fetched = (
                    await session.execute(select(Team).where(Team.slug == "acme"))
                ).scalar_one()
                assert fetched.id == team.id
                assert fetched.created_at is not None
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    asyncio.run(scenario())
