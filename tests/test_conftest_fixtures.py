from sqlalchemy import select

from app.models import Team


async def test_db_session_is_isolated_across_tests(db_session):
    count = await db_session.scalar(select(Team).limit(1))
    assert count is None

    db_session.add(Team(name="leftover-team"))
    await db_session.commit()


async def test_db_session_does_not_see_previous_test_writes(db_session):
    team = await db_session.scalar(select(Team).where(Team.name == "leftover-team"))
    assert team is None
