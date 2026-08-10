from fastapi import APIRouter, Depends

from app.security import get_current_team

router = APIRouter(prefix="/v1", dependencies=[Depends(get_current_team)])
