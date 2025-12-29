import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional, List

from vo.model.message_type import MessageType
from vo.model.radio_status import RadioStatus
from vo.model.user import User
from fastapi import WebSocket
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RadioConnectionManager:
    def __init__(self):
        self.active_users: Dict[str, User] = {}
        self.current_speaker_id: Optional[str] = None
        self.waiting_queue: List[str] = []  # FIFO очередь
        self._lock = asyncio.Lock()

    async def connect_user(self, websocket: WebSocket, username: str) -> str:
        """Подключение нового пользователя"""
        await websocket.accept()

        # Генерируем уникальный ID
        user_id = f"{username}_{uuid.uuid4().hex[:8]}"

        # Создаем объект пользователя
        user = User(
            id=user_id,
            username=username,
            websocket=websocket,
            connected_at=datetime.now()
        )

        async with self._lock:
            self.active_users[user_id] = user

        logger.info(f"🟢 ПОДКЛЮЧЕНИЕ: {username} ({user_id})")

        # Отправляем подтверждение подключения
        await self._send_to_user(user_id, {
            "type": MessageType.CONNECTED,
            "user_id": user_id,
            "username": username,
            "message": "Connected to radio server",
            "server_time": datetime.now().isoformat()
        })

        # Отправляем текущий статус
        await self._send_status_to_user(user_id)

        # Уведомляем всех о новом пользователе
        await self._broadcast_excluding(user_id, {
            "type": MessageType.USER_JOINED,
            "user_id": user_id,
            "username": username,
            "total_users": len(self.active_users),
            "timestamp": datetime.now().isoformat()
        })

        return user_id

    async def disconnect_user(self, user_id: str):
        """Отключение пользователя"""
        async with self._lock:
            if user_id not in self.active_users:
                return

            user = self.active_users[user_id]
            username = user.username

            # Удаляем из очереди ожидания
            if user_id in self.waiting_queue:
                self.waiting_queue.remove(user_id)

            # Если это текущий говорящий - освобождаем
            if self.current_speaker_id == user_id:
                self.current_speaker_id = None
                await self._handle_speaker_released(user_id, "disconnected")

            # Удаляем пользователя
            del self.active_users[user_id]

            logger.info(f"🔴 ОТКЛЮЧЕНИЕ: {username} ({user_id})")

            # Уведомляем всех об отключении
            await self._broadcast_to_all({
                "type": MessageType.USER_LEFT,
                "user_id": user_id,
                "username": username,
                "total_users": len(self.active_users),
                "timestamp": datetime.now().isoformat()
            })

    async def request_speak(self, user_id: str) -> Dict:
        """Запрос на право говорить"""
        async with self._lock:
            if user_id not in self.active_users:
                return {
                    "type": MessageType.ERROR,
                    "message": "User not connected"
                }

            # Если никто не говорит - даем право
            if self.current_speaker_id is None:
                self.current_speaker_id = user_id
                self.active_users[user_id].is_speaking = True

                username = self.active_users[user_id].username
                logger.info(f"🎤 НАЧАЛ ГОВОРИТЬ: {username}")

                # Уведомляем всех
                await self._broadcast_to_all({
                    "type": MessageType.SPEAKER_CHANGED,
                    "speaker_id": user_id,
                    "speaker_name": username,
                    "timestamp": datetime.now().isoformat()
                })

                return {
                    "type": MessageType.SPEAK_GRANTED,
                    "message": "You can speak now",
                    "timestamp": datetime.now().isoformat()
                }

            # Если уже говорим - добавляем в очередь
            else:
                if user_id not in self.waiting_queue:
                    self.waiting_queue.append(user_id)

                position = self.waiting_queue.index(user_id) + 1

                return {
                    "type": MessageType.SPEAK_DENIED,
                    "message": f"You are in queue at position {position}",
                    "position": position,
                    "current_speaker": self.active_users[self.current_speaker_id].username,
                    "timestamp": datetime.now().isoformat()
                }

    async def release_speak(self, user_id: str) -> Dict:
        """Освобождение права говорить"""
        async with self._lock:
            if self.current_speaker_id != user_id:
                # Если пользователь в очереди - удаляем
                if user_id in self.waiting_queue:
                    self.waiting_queue.remove(user_id)
                    return {
                        "type": MessageType.SPEAK_RELEASED,
                        "message": "Removed from queue",
                        "timestamp": datetime.now().isoformat()
                    }
                return {
                    "type": MessageType.ERROR,
                    "message": "You are not the current speaker",
                    "timestamp": datetime.now().isoformat()
                }

            # Освобождаем право
            self.current_speaker_id = None
            self.active_users[user_id].is_speaking = False

            await self._handle_speaker_released(user_id, "released")

            return {
                "type": MessageType.SPEAK_RELEASED,
                "message": "Speaking rights released",
                "timestamp": datetime.now().isoformat()
            }

    async def _handle_speaker_released(self, old_speaker_id: str, reason: str):
        """Обработка освобождения права говорить"""
        old_speaker_name = self.active_users[old_speaker_id].username

        # Уведомляем об освобождении
        await self._broadcast_to_all({
            "type": MessageType.SPEAKER_CHANGED,
            "speaker_id": None,
            "speaker_name": None,
            "previous_speaker": old_speaker_name,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        # Даем право следующему в очереди
        if self.waiting_queue:
            next_speaker_id = self.waiting_queue.pop(0)
            self.current_speaker_id = next_speaker_id
            self.active_users[next_speaker_id].is_speaking = True

            next_speaker_name = self.active_users[next_speaker_id].username
            logger.info(f"➡️ ТЕПЕРЬ ГОВОРИТ: {next_speaker_name}")

            # Уведомляем всех о новом говорящем
            await self._broadcast_to_all({
                "type": MessageType.SPEAKER_CHANGED,
                "speaker_id": next_speaker_id,
                "speaker_name": next_speaker_name,
                "timestamp": datetime.now().isoformat()
            })

            # Уведомляем нового говорящего
            await self._send_to_user(next_speaker_id, {
                "type": MessageType.SPEAK_GRANTED,
                "message": "You can speak now",
                "timestamp": datetime.now().isoformat()
            })

    async def process_audio_chunk(self, user_id: str, audio_data: bytes):
        """
        ОСНОВНОЙ МЕТОД: обработка аудио чанка в реальном времени
        Вызывается для каждого чанка пока пользователь держит кнопку PTT
        """
        # Быстрая проверка без блокировки
        if self.current_speaker_id != user_id:
            logger.warning(f"⚠️ Попытка передачи без права: {user_id}")
            return

        # Трансляция всем остальным пользователям
        await self._broadcast_audio(user_id, audio_data)

    async def _broadcast_audio(self, sender_id: str, audio_data: bytes):
        """Трансляция аудио всем, кроме отправителя"""
        # Создаем задачи для параллельной отправки
        tasks = []

        for user_id, user in self.active_users.items():
            if user_id != sender_id:
                try:
                    # Отправляем байты аудио
                    tasks.append(user.websocket.send_bytes(audio_data))
                except Exception as e:
                    logger.error(f"Ошибка отправки аудио {user.username}: {e}")
                    # Планируем отключение проблемного пользователя
                    asyncio.create_task(self.disconnect_user(user_id))

        # Параллельная отправка
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Логируем ошибки
            for result in results:
                if isinstance(result, Exception):
                    logger.debug(f"Ошибка при отправке аудио: {result}")

    async def get_status(self) -> RadioStatus:
        """Получение текущего статуса радио"""
        async with self._lock:
            return RadioStatus(
                current_speaker=self.current_speaker_id,
                current_speaker_name=self.active_users[
                    self.current_speaker_id].username if self.current_speaker_id else None,
                waiting_queue=self.waiting_queue.copy(),
                waiting_names=[self.active_users[uid].username for uid in self.waiting_queue],
                connected_users=list(self.active_users.keys()),
                connected_usernames=[user.username for user in self.active_users.values()],
                total_connected=len(self.active_users),
                server_time=datetime.now()
            )

    async def _send_status_to_user(self, user_id: str):
        """Отправка статуса конкретному пользователю"""
        status = await self.get_status()
        await self._send_to_user(user_id, {
            "type": MessageType.STATUS,
            "status": {
                "current_speaker": status.current_speaker,
                "current_speaker_name": status.current_speaker_name,
                "waiting_queue": status.waiting_queue,
                "waiting_names": status.waiting_names,
                "connected_users": status.connected_users,
                "connected_usernames": status.connected_usernames,
                "total_connected": status.total_connected
            },
            "timestamp": status.server_time.isoformat()
        })

    async def _send_to_user(self, user_id: str, message: Dict):
        """Отправка сообщения конкретному пользователю"""
        if user_id in self.active_users:
            try:
                await self.active_users[user_id].websocket.send_text(
                    json.dumps(message)
                )
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
                asyncio.create_task(self.disconnect_user(user_id))

    async def _broadcast_to_all(self, message: Dict):
        """Отправка сообщения всем пользователям"""
        json_message = json.dumps(message)
        tasks = []

        for user in self.active_users.values():
            try:
                tasks.append(user.websocket.send_text(json_message))
            except Exception as e:
                logger.error(f"Ошибка broadcast пользователю {user.username}: {e}")
                asyncio.create_task(self.disconnect_user(user.id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _broadcast_excluding(self, exclude_id: str, message: Dict):
        """Отправка сообщения всем, кроме указанного пользователя"""
        json_message = json.dumps(message)
        tasks = []

        for user in self.active_users.values():
            if user.id != exclude_id:
                try:
                    tasks.append(user.websocket.send_text(json_message))
                except Exception as e:
                    logger.error(f"Ошибка broadcast пользователю {user.username}: {e}")
                    asyncio.create_task(self.disconnect_user(user.id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)