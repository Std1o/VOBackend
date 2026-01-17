from fastapi import APIRouter, WebSocket, Depends, HTTPException
from starlette import status
from starlette.websockets import WebSocketDisconnect
from vo.model.chat import BaseMessage
from vo.service.auth import get_current_user
from vo.service.chat import ChatService
from typing import Dict, List

router = APIRouter(prefix='/chat')

# Простой менеджер для хранения активных соединений
active_connections: Dict[int, List[WebSocket]] = {}


@router.websocket("/{channel_id}")
async def chat(websocket: WebSocket,
               channel_id: int,
               service: ChatService = Depends()):
    await websocket.accept()
    user = None
    try:
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
            # Получаем параметры запроса от клиента
            params_data = await websocket.receive_json()
            if params_data.get('command') == "get":
                messages = await service.get_messages(channel_id)
                await websocket.send_json(messages)
            else:
                params = BaseMessage(**params_data)
                # Сохраняем сообщение в БД
                saved_message = await service.create_message(params)

                # Отправляем сообщение всем клиентам в канале
                if channel_id in active_connections:
                    # Создаем копию списка для безопасной итерации
                    connections = active_connections[channel_id].copy()
                    disconnected = []

                    for connection in connections:
                        try:
                            # Отправляем всем, включая отправителя
                            await connection.send_json(saved_message)
                        except Exception as e:
                            # Помечаем отключенные соединения
                            print(f"Failed to send to connection: {e}")
                            disconnected.append(connection)

                    # Удаляем отключенные соединения
                    for connection in disconnected:
                        if connection in active_connections.get(channel_id, []):
                            active_connections[channel_id].remove(connection)

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

        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        print(f"Error in WebSocket connection: {e}")