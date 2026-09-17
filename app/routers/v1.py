from fastapi import APIRouter, Depends

from app.core.security import get_current_team
from app.routers import images, jobs

router = APIRouter(prefix="/v1", dependencies=[Depends(get_current_team)])
router.include_router(images.router)
router.include_router(jobs.router)
