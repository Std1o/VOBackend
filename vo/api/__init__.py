from fastapi import APIRouter
from .radio import router as websocket_radio_router
from .auth import router as auth_router

router = APIRouter()
router.include_router(websocket_radio_router)
router.include_router(auth_router)