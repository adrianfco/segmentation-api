import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Team
from app.schemas.team import TeamResponse

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team
