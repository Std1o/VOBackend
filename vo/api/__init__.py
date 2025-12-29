from fastapi import APIRouter
from .radio import router as websocket_radio_router

router = APIRouter()
router.include_router(websocket_radio_router)