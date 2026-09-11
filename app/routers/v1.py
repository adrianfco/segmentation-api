from fastapi import APIRouter, Depends

from app.routers import images
from app.security import get_current_team

router = APIRouter(prefix="/v1", dependencies=[Depends(get_current_team)])
router.include_router(images.router)
