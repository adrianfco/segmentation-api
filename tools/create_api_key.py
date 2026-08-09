import argparse
import asyncio

from sqlalchemy import select

from app import db
from app.models import ApiKey, Team
from app.security import generate_api_key, hash_api_key


async def create_api_key(team_name: str, key_name: str) -> tuple[ApiKey, str]:
    async with db.get_sessionmaker()() as session:
        team = await session.scalar(select(Team).where(Team.name == team_name))
        if team is None:
            raise SystemExit(f"Team not found: {team_name}")

        raw_key = generate_api_key()
        api_key = ApiKey(team_id=team.id, name=key_name, key_hash=hash_api_key(raw_key))
        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)
        return api_key, raw_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("team_name")
    parser.add_argument("key_name")
    args = parser.parse_args()

    api_key, raw_key = asyncio.run(create_api_key(args.team_name, args.key_name))

    print(f"Created API key {api_key.id} ({api_key.name}) for team {args.team_name}")
    print(f"Key (store this now, it will not be shown again): {raw_key}")


if __name__ == "__main__":
    main()
