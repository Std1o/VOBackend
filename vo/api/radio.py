import logging
from datetime import datetime
from typing import Dict, List, Optional
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


# ========== REST API endpoints для статуса и пользователей ==========

@router.get("/connected_users/{channel_id}")
async def get_connected_users(
        channel_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получить текущий статус канала (REST API)"""
    status = await radio_manager.get_channel_status(channel_id)
    if not status:
        raise HTTPException(status_code=404, detail="Channel not found or empty")

    return status.connected_usernames


@router.post("/recordings/start/{channel_id}")
async def start_recording(
        channel_id: int,
        current_user: User = Depends(get_current_user),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Начать запись эфира в канале"""
    # Проверяем права (опционально)
    # Только модераторы или владельцы могут записывать

    result = await radio_manager.start_recording(channel_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.post("/recordings/stop/{channel_id}")
async def stop_recording(
        channel_id: int,
        current_user: User = Depends(get_current_user),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Остановить запись эфира в канале"""
    result = await radio_manager.stop_recording(channel_id, current_user.username)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/recordings/status/{channel_id}")
async def get_recording_status(
        channel_id: int,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получить статус записи для канала"""
    return await radio_manager.get_recording_status(channel_id)


@router.get("/recordings/list")
async def list_recordings(
        channel_id: Optional[int] = Query(None, description="Filter by channel ID"),
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Получить список всех записей"""
    return await radio_manager.get_recordings_list(channel_id)


@router.get("/recordings/download/{filename}")
async def download_recording(
        filename: str,
        radio_manager: RadioConnectionManager = Depends(get_radio_manager)
):
    """Скачать файл записи"""
    from fastapi.responses import FileResponse
    import os

    filepath = os.path.join("records", filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording file not found")

    return FileResponse(
        filepath,
        media_type="audio/mpeg",
        filename=filename
    )


# ========== Вспомогательные функции ==========

async def _handle_client_message(
        radio_manager: RadioConnectionManager,
        user_id: str,
        channel_id: int,
        message: Dict
):
    """Обработка сообщений от клиента"""
    message_type = message.get("type")
    speaker_name = message.get("speaker_name")

    if message_type == "speak_request":
        # Запрос на право говорить
        response = await radio_manager.request_speak(user_id, channel_id, speaker_name)
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
