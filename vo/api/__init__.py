from fastapi import APIRouter
from .radio import router as websocket_radio_router
from .auth import router as auth_router
from .channel import router as channel_router
from .channel_admins import router as channel_admins_router
from .channel_management import router as channel_management_router
from .chat import router as chat_router

router = APIRouter()
router.include_router(websocket_radio_router)
router.include_router(auth_router)
router.include_router(channel_router)
router.include_router(channel_admins_router)
router.include_router(channel_management_router)
router.include_router(chat_router)