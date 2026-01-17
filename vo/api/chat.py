from fastapi import APIRouter, WebSocket, Depends, HTTPException
from starlette import status
from starlette.websockets import WebSocketDisconnect
from vo.model.chat import BaseMessage
from vo.service.auth import get_current_user
from vo.service.chat import ChatService

router = APIRouter(prefix='/chat')

@router.websocket("/{channel_id}")
async def get_results_via_websocket(websocket: WebSocket,
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

        while True:
            # Получаем параметры запроса от клиента
            params_data = await websocket.receive_json()
            if params_data['command'] == "get":
                messages = await service.get_messages(channel_id)
                await websocket.send_json(messages)
            else:
                params = BaseMessage(**params_data)
                await websocket.send_json(service.create_message(params))
    except WebSocketDisconnect:
        print(f"WebSocket connection closed for course_id={channel_id}.")
    except Exception as e:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        print(f"Error in WebSocket connection: {e}")