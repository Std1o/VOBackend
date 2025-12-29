import logging
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vo.model.message_type import MessageType
from vo.service.radio_connection_manager import RadioConnectionManager
import json

router = APIRouter()

radio_manager = RadioConnectionManager()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@router.websocket("/ws/{username}")
async def websocket_radio(websocket: WebSocket, username: str):
    """
    Основной WebSocket endpoint для подключения к рации.

    Клиент отправляет:
    1. JSON команды (управление)
    2. Бинарные данные (аудио чанки в реальном времени)
    """

    # Подключаем пользователя
    user_id = await radio_manager.connect_user(websocket, username)

    try:
        while True:
            # Ожидаем данные от клиента
            data = await websocket.receive()

            if "text" in data:
                # Обработка текстовых команд
                try:
                    message = json.loads(data["text"])
                    await _handle_client_message(user_id, message)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from {username}: {e}")
                    await radio_manager._send_to_user(user_id, {
                        "type": MessageType.ERROR,
                        "message": "Invalid JSON format"
                    })

            elif "bytes" in data:
                # ПОЛУЧЕНИЕ АУДИО ЧАНКА В РЕАЛЬНОМ ВРЕМЕНИ
                # data["bytes"] содержит аудио данные с клиента
                await radio_manager.process_audio_chunk(user_id, data["bytes"])

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {username}")
        await radio_manager.disconnect_user(user_id)
    except Exception as e:
        logger.error(f"Error in WebSocket for {username}: {e}")
        await radio_manager.disconnect_user(user_id)

@router.get("/api/status")
async def api_get_status():
    """Получить текущий статус радио (REST API)"""
    status = await radio_manager.get_status()
    return {
        "current_speaker": status.current_speaker,
        "current_speaker_name": status.current_speaker_name,
        "waiting_queue": status.waiting_queue,
        "waiting_names": status.waiting_names,
        "connected_users": status.connected_users,
        "connected_usernames": status.connected_usernames,
        "total_connected": status.total_connected,
        "server_time": status.server_time.isoformat()
    }


@router.get("/api/users")
async def api_get_users():
    """Получить список подключенных пользователей"""
    status = await radio_manager.get_status()
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
        "users": users_info,
        "total": status.total_connected
    }

async def _handle_client_message(user_id: str, message: Dict):
    """Обработка сообщений от клиента"""
    message_type = message.get("type")

    if message_type == "speak_request":
        # Запрос на право говорить
        response = await radio_manager.request_speak(user_id)
        await radio_manager._send_to_user(user_id, response)

    elif message_type == "speak_release":
        # Освобождение права говорить
        response = await radio_manager.release_speak(user_id)
        await radio_manager._send_to_user(user_id, response)

    elif message_type == "get_status":
        # Запрос статуса
        await radio_manager._send_status_to_user(user_id)

    elif message_type == "ping":
        # Keep-alive ping
        await radio_manager._send_to_user(user_id, {
            "type": MessageType.PONG,
            "timestamp": datetime.now().isoformat()
        })

    else:
        await radio_manager._send_to_user(user_id, {
            "type": MessageType.ERROR,
            "message": f"Unknown message type: {message_type}"
        })