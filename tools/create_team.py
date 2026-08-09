import argparse
import asyncio

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Team


async def create_team(name: str) -> Team:
    async with db.get_sessionmaker()() as session:
        team = Team(name=name)
        session.add(team)
        await session.commit()
        await session.refresh(team)
        return team


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()

    try:
        team = asyncio.run(create_team(args.name))
    except IntegrityError as exc:
        raise SystemExit(f"Team name already exists: {args.name}") from exc

    print(f"Created team {team.id} ({team.name})")


if __name__ == "__main__":
    main()
