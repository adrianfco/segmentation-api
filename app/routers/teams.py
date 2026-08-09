import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Team
from app.schemas.team import TeamCreate, TeamResponse

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate, session: AsyncSession = Depends(get_session)) -> Team:
    team = Team(name=payload.name)
    session.add(team)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Team name already exists"
        ) from exc
    await session.refresh(team)
    return team


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team
