from fastapi import APIRouter, WebSocket, Depends, HTTPException, Query
from starlette import status
from starlette.websockets import WebSocketDisconnect
from vo.model.chat import BaseMessage
from vo.service.auth import get_current_user
from vo.service.chat import ChatService
from typing import Dict, List
import json

router = APIRouter(prefix='/chat')

# Простой менеджер для хранения активных соединений
active_connections: Dict[int, List[WebSocket]] = {}


@router.websocket("/{channel_id}")
async def chat(
        websocket: WebSocket,
        channel_id: int,
        timezone: str = Query('UTC'),  # Получаем часовой пояс из query параметра
        service: ChatService = Depends()
):
    await websocket.accept()
    user = None
    client_timezone = timezone  # Сохраняем часовой пояс клиента

    try:
        # Аутентификация
        token = websocket.headers.get("Authorization")
        if not token or not token.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")

        token = token.split(" ")[1]  # Убираем "Bearer"
        user = get_current_user(token)

        # Регистрируем соединение
        if channel_id not in active_connections:
            active_connections[channel_id] = []
        active_connections[channel_id].append(websocket)

        while True:
            try:
                # Получаем данные от клиента (оригинальный формат)
                data = await websocket.receive_text()
                params_data = json.loads(data)

                # Проверяем команду
                if params_data.get('command') == "get":
                    # Получаем сообщения с учетом часового пояса клиента
                    messages = await service.get_messages(channel_id, client_timezone)
                    await websocket.send_json(messages)

                else:
                    # Это сообщение для отправки (оригинальный формат)
                    # params_data содержит BaseMessage напрямую
                    base_message = BaseMessage(**params_data)

                    # Сохраняем сообщение с указанием часового пояса клиента
                    updated_messages = await service.create_message(base_message, client_timezone)

                    # Отправляем обновленные сообщения всем в канале
                    if channel_id in active_connections:
                        connections = active_connections[channel_id].copy()
                        disconnected = []

                        for connection in connections:
                            try:
                                await connection.send_json(updated_messages)
                            except Exception as e:
                                disconnected.append(connection)

                        # Удаляем отключенные соединения
                        for connection in disconnected:
                            if connection in active_connections.get(channel_id, []):
                                active_connections[channel_id].remove(connection)

            except json.JSONDecodeError:
                await websocket.send_json({
                    "error": "Invalid JSON format"
                })

    except WebSocketDisconnect:
        print(f"WebSocket connection closed for channel_id={channel_id}.")
        # Удаляем соединение из активных
        if channel_id in active_connections and websocket in active_connections[channel_id]:
            active_connections[channel_id].remove(websocket)
            # Очищаем пустой список
            if not active_connections[channel_id]:
                del active_connections[channel_id]

    except Exception as e:
        # Удаляем соединение при ошибке
        if channel_id in active_connections and websocket in active_connections[channel_id]:
            active_connections[channel_id].remove(websocket)
            if not active_connections[channel_id]:
                del active_connections[channel_id]

        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except:
            pass