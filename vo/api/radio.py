import logging
from datetime import datetime
from typing import Dict, List
from sqlalchemy.orm import Session

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, Body

from vo.database import get_session
from vo.model.auth import User
from vo.model.message_type import MessageType
from vo.service.auth import get_current_user
from vo.service.radio_connection_manager import RadioConnectionManager
import json

router = APIRouter()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


radio_manager = RadioConnectionManager()

def get_radio_manager_with_session():
    """Фабрика для получения менеджера с установленной сессией"""
    def _get_manager(session: Session = Depends(get_session)):
        # Устанавливаем сессию БД в менеджер
        radio_manager.set_session(session)
        return radio_manager
    return _get_manager

# Используем эту фабрику в зависимостях
get_radio_manager = get_radio_manager_with_session()


# ========== WebSocket endpoints ==========

@router.websocket("/ws/{channel_id}/{username}")
async def websocket_radio(
    websocket: WebSocket,
    channel_id: int,
    username: str,
    radio_manager: RadioConnectionManager = Depends(get_radio_manager)  # <-- Используем общий менеджер!
):
    """
    Основной WebSocket endpoint для подключения к рации.
    """
    # Подключаем пользователя к каналу
    user_id = await radio_manager.connect_user(websocket, username, channel_id)
    if not user_id:
        await websocket.close(code=1008, reason="Channel access denied")
        return

    try:
        while True:
            # Ожидаем данные от клиента
            data = await websocket.receive()

            if "text" in data:
                # Обработка текстовых команд
                try:
                    message = json.loads(data["text"])
                    await _handle_client_message(radio_manager, user_id, channel_id, message)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from {username}: {e}")
                    await radio_manager._send_to_user(channel_id, user_id, {
                        "type": MessageType.ERROR,
                        "message": "Invalid JSON format"
                    })

            elif "bytes" in data:
                # ПОЛУЧЕНИЕ АУДИО ЧАНКА В РЕАЛЬНОМ ВРЕМЕНИ
                await radio_manager.process_audio_chunk(user_id, channel_id, data["bytes"])

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {username} from channel {channel_id}")
        await radio_manager.disconnect_user(user_id, channel_id)
    except Exception as e:
        logger.error(f"Error in WebSocket for {username}: {e}")
        await radio_manager.disconnect_user(user_id, channel_id)


# ========== REST API endpoints для управления каналами ==========


@router.get("/api/channels")
async def api_list_channels(
        include_participants: bool = Query(False, description="Включить информацию об участниках"),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получение списка всех каналов"""
    channels = await radio_manager.list_channels(include_participants)
    return {"channels": channels, "total": len(channels)}


@router.get("/api/user/{user_id}/channels")
async def api_get_user_channels(
        user_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получение списка каналов пользователя"""
    channels = await radio_manager.get_user_channels(user_id)
    return {"user_id": user_id, "channels": channels, "total": len(channels)}


@router.get("/api/channel/{channel_id}")
async def api_get_channel_info(
        channel_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получение информации о канале"""
    channel_info = await radio_manager.get_channel_info(channel_id)
    if not channel_info:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel_info


@router.post("/api/channel/{channel_id}/add_user")
async def api_add_user_to_channel(
        channel_id: int,
        user_id: int = Query(..., description="ID пользователя для добавления"),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Добавление пользователя в канал"""
    result = await radio_manager.add_user_to_channel(user_id, channel_id)

    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["message"])


@router.delete("/api/channel/{channel_id}/remove_user")
async def api_remove_user_from_channel(
        channel_id: int,
        user_id: int = Query(..., description="ID пользователя для удаления"),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Удаление пользователя из канала"""
    result = await radio_manager.remove_user_from_channel(user_id, channel_id)

    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["message"])


@router.delete("/api/channel/{channel_id}")
async def api_delete_channel(
        channel_id: int,
        requesting_user_id: int = Query(..., description="ID пользователя, запрашивающего удаление"),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Удаление канала (только владельцем)"""
    result = await radio_manager.delete_channel(channel_id, requesting_user_id)

    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["message"])


# ========== REST API endpoints для статуса и пользователей ==========

@router.get("/status/{channel_id}")
async def api_get_status(
        channel_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получить текущий статус канала (REST API)"""
    status = await radio_manager.get_channel_status(channel_id)
    if not status:
        raise HTTPException(status_code=404, detail="Channel not found or empty")

    return {
        "connected_usernames": status.connected_usernames,
    }


@router.get("/api/channel/{channel_id}/users")
async def api_get_channel_users(
        channel_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получить список подключенных пользователей в канале"""
    status = await radio_manager.get_channel_status(channel_id)
    if not status:
        raise HTTPException(status_code=404, detail="Channel not found or empty")

    users_info = []

    for user_id, username in zip(status.connected_users, status.connected_usernames):
        users_info.append({
            "id": user_id,
            "username": username,
            "is_speaker": user_id == status.current_speaker,
            "in_queue": user_id in status.waiting_queue,
            "queue_position": status.waiting_queue.index(user_id) + 1 if user_id in status.waiting_queue else None
        })

    return {
        "channel_id": channel_id,
        "users": users_info,
        "total": status.total_connected
    }


# ========== Вспомогательные функции ==========

async def _handle_client_message(
        radio_manager: RadioConnectionManager,
        user_id: str,
        channel_id: int,
        message: Dict
):
    """Обработка сообщений от клиента"""
    message_type = message.get("type")

    if message_type == "speak_request":
        # Запрос на право говорить
        response = await radio_manager.request_speak(user_id, channel_id)
        await radio_manager._send_to_user(channel_id, user_id, response)

    elif message_type == "speak_release":
        # Освобождение права говорить
        response = await radio_manager.release_speak(user_id, channel_id)
        await radio_manager._send_to_user(channel_id, user_id, response)

    elif message_type == "get_status":
        # Запрос статуса
        await radio_manager._send_status_to_user(channel_id, user_id)

    elif message_type == "ping":
        # Keep-alive ping
        await radio_manager._send_to_user(channel_id, user_id, {
            "type": MessageType.PONG,
            "timestamp": datetime.now().isoformat()
        })

    else:
        await radio_manager._send_to_user(channel_id, user_id, {
            "type": MessageType.ERROR,
            "message": f"Unknown message type: {message_type}"
        })