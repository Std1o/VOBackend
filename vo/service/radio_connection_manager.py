import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, List

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from vo.model.message_type import MessageType
from vo.model.radio_status import RadioStatus
from vo.model.user import User
from .. import tables
from ..tables import Channel, User as DBUser, Participants
from .radio_recorder import RadioRecorder
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RadioConnectionManager:
    def __init__(self):
        # Храним активные соединения по каналам: channel_id -> {user_id: User}
        self.active_channels: Dict[int, Dict[str, User]] = defaultdict(dict)
        self.current_speakers: Dict[int, Optional[str]] = defaultdict(lambda: None)
        self.waiting_queues: Dict[int, List[str]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._db_lock = asyncio.Lock()
        self.recorder = RadioRecorder(records_dir="records")

    def set_session(self, session: Session):
        """Устанавливаем сессию БД (вызывается при каждом запросе)"""
        self.session = session

    # ========== Основные методы для подключения пользователей ==========

    async def _validate_channel_access(self, channel_id: int, username: str) -> bool:
        """Проверка доступа пользователя к каналу в БД"""
        async with self._db_lock:
            # Проверяем существование канала
            channel = self.session.query(Channel).filter(Channel.id == channel_id).first()
            if not channel:
                logger.error(f"❌ Канал {channel_id} не найден в БД")
                return False

            # Находим пользователя по username
            user = self.session.query(DBUser).filter(DBUser.username == username).first()
            if not user:
                # Если пользователя нет, создаем его
                try:
                    user = DBUser(username=username)
                    self.session.add(user)
                    self.session.commit()
                    self.session.refresh(user)
                    logger.info(f"✅ Создан новый пользователь: {username} (ID: {user.id})")
                except Exception as e:
                    logger.error(f"❌ Ошибка создания пользователя: {e}")
                    return False

            # Проверяем участника канала
            participant = self.session.query(Participants).filter(
                Participants.user_id == user.id,
                Participants.channel_id == channel_id
            ).first()

            if not participant:
                # Автоматически добавляем как участника (без прав)
                try:
                    participant = Participants(
                        user_id=user.id,
                        channel_id=channel_id,
                        is_moderator=False,
                        is_owner=False
                    )
                    self.session.add(participant)
                    self.session.commit()
                    logger.info(f"✅ Пользователь {username} добавлен в канал {channel_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка добавления участника: {e}")
                    return False

            return True

    async def connect_user(self, websocket: WebSocket, username: str, channel_id: int) -> Optional[str]:
        """Подключение нового пользователя к каналу"""
        # Проверяем доступ к каналу
        if not await self._validate_channel_access(channel_id, username):
            return None

        await websocket.accept()

        # Генерируем уникальный ID для WebSocket соединения
        ws_user_id = f"{username}_{uuid.uuid4().hex[:8]}"

        # Создаем объект пользователя для WebSocket
        user = User(
            id=ws_user_id,
            username=username,
            websocket=websocket,
            connected_at=datetime.now()
        )

        async with self._lock:
            self.active_channels[channel_id][ws_user_id] = user

        logger.info(f"🟢 ПОДКЛЮЧЕНИЕ: {username} ({ws_user_id}) к каналу {channel_id}")

        # Отправляем подтверждение подключения
        await self._send_to_user(channel_id, ws_user_id, {
            "type": MessageType.CONNECTED,
            "user_id": ws_user_id,
            "username": username,
            "channel_id": channel_id,
            "message": f"Connected to channel {channel_id}",
            "server_time": datetime.now().isoformat()
        })

        # Отправляем текущий статус канала
        await self._send_status_to_user(channel_id, ws_user_id)

        await self._send_recording_status_to_user(channel_id, ws_user_id)

        # Уведомляем всех в канале о новом пользователе
        await self._broadcast_excluding(channel_id, ws_user_id, {
            "type": MessageType.USER_JOINED,
            "user_id": ws_user_id,
            "username": username,
            "channel_id": channel_id,
            "total_users": len(self.active_channels[channel_id]),
            "timestamp": datetime.now().isoformat()
        })

        return ws_user_id

    async def disconnect_user(self, ws_user_id: str, channel_id: int):
        """Отключение пользователя от канала"""
        async with self._lock:
            if channel_id not in self.active_channels or ws_user_id not in self.active_channels[channel_id]:
                return

            user = self.active_channels[channel_id][ws_user_id]
            username = user.username

            # Удаляем из очереди ожидания
            if ws_user_id in self.waiting_queues[channel_id]:
                self.waiting_queues[channel_id].remove(ws_user_id)

            # Если это текущий говорящий - освобождаем
            if self.current_speakers[channel_id] == ws_user_id:
                self.current_speakers[channel_id] = None
                await self._handle_speaker_released(channel_id, ws_user_id, "disconnected")

            # Удаляем пользователя
            del self.active_channels[channel_id][ws_user_id]

            # Если канал пустой - очищаем
            if not self.active_channels[channel_id]:
                if channel_id in self.active_channels:
                    del self.active_channels[channel_id]
                if channel_id in self.current_speakers:
                    del self.current_speakers[channel_id]
                if channel_id in self.waiting_queues:
                    del self.waiting_queues[channel_id]

            logger.info(f"🔴 ОТКЛЮЧЕНИЕ: {username} ({ws_user_id}) от канала {channel_id}")

            # Уведомляем всех в канале об отключении
            await self._broadcast_to_channel(channel_id, {
                "type": MessageType.USER_LEFT,
                "user_id": ws_user_id,
                "username": username,
                "channel_id": channel_id,
                "total_users": len(self.active_channels.get(channel_id, {})),
                "timestamp": datetime.now().isoformat()
            })

    async def get_channel_owner(self, channel_id: int) -> tables.Participants:
        statement = select(tables.Participants).filter_by(channel_id=channel_id, is_owner=True)
        return self.session.execute(statement).scalars().first()

    async def get_user(self, user_id: int) -> tables.User:
        statement = select(tables.User).filter_by(id=user_id)
        return self.session.execute(statement).scalars().first()

    async def request_speak(self, ws_user_id: str, channel_id: int, speaker_name: str) -> Dict:
        """Запрос на право говорить в канале"""
        async with self._lock:
            if channel_id not in self.active_channels or ws_user_id not in self.active_channels[channel_id]:
                return {
                    "type": MessageType.ERROR,
                    "message": "User not connected"
                }

            # Если никто не говорит - даем право
            if self.current_speakers[channel_id] is None:
                self.current_speakers[channel_id] = ws_user_id
                self.active_channels[channel_id][ws_user_id].is_speaking = True

                username = self.active_channels[channel_id][ws_user_id].username
                logger.info(f"🎤 НАЧАЛ ГОВОРИТЬ в канале {channel_id}: {username}")
                owner = await self.get_channel_owner(channel_id)
                user = await self.get_user(owner.user_id)
                logger.info(f"Премиум {user.premium}: {date.today()}")
                logger.info(f"Дата {user.premium >= date.today():}")
                if user.premium >= date.today():
                    await self.start_recording(channel_id, speaker_name)

                # Уведомляем всех в канале
                await self._broadcast_to_channel(channel_id, {
                    "type": MessageType.SPEAKER_CHANGED,
                    "speaker_id": ws_user_id,
                    "speaker_name": username,
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                })

                return {
                    "type": MessageType.SPEAK_GRANTED,
                    "message": "You can speak now",
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                }

            # Если уже говорим - добавляем в очередь
            else:
                if ws_user_id not in self.waiting_queues[channel_id]:
                    self.waiting_queues[channel_id].append(ws_user_id)

                position = self.waiting_queues[channel_id].index(ws_user_id) + 1

                return {
                    "type": MessageType.SPEAK_DENIED,
                    "message": f"You are in queue at position {position}",
                    "position": position,
                    "current_speaker": self.active_channels[channel_id][self.current_speakers[channel_id]].username,
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                }

    async def release_speak(self, ws_user_id: str, channel_id: int) -> Dict:
        """Освобождение права говорить в канале"""
        async with self._lock:
            # ВСЕГДА удаляем из очереди, где бы пользователь ни был
            if ws_user_id in self.waiting_queues[channel_id]:
                self.waiting_queues[channel_id].remove(ws_user_id)
                logger.info(f"🗑️ Удален из очереди: {ws_user_id}")

            if self.current_speakers[channel_id] != ws_user_id:
                return {
                    "type": MessageType.SPEAK_RELEASED,
                    "message": "Removed from queue",
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                }

            # Освобождаем право
            self.current_speakers[channel_id] = None
            self.active_channels[channel_id][ws_user_id].is_speaking = False

            await self.stop_recording(channel_id)
            await self._handle_speaker_released(channel_id, ws_user_id, "released")

            return {
                "type": MessageType.SPEAK_RELEASED,
                "message": "Speaking rights released",
                "channel_id": channel_id,
                "timestamp": datetime.now().isoformat()
            }

    async def _handle_speaker_released(self, channel_id: int, old_speaker_id: str, reason: str):
        """Обработка освобождения права говорить"""
        if channel_id not in self.active_channels or old_speaker_id not in self.active_channels[channel_id]:
            return

        old_speaker_name = self.active_channels[channel_id][old_speaker_id].username

        # Уведомляем об освобождении
        await self._broadcast_to_channel(channel_id, {
            "type": MessageType.SPEAKER_CHANGED,
            "speaker_id": None,
            "speaker_name": None,
            "previous_speaker": old_speaker_name,
            "channel_id": channel_id,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        # Даем право следующему в очереди
        if self.waiting_queues[channel_id]:
            next_speaker_id = self.waiting_queues[channel_id].pop(0)

            # Проверяем, что следующий не равен старому говорящему
            if next_speaker_id == old_speaker_id:
                logger.warning(f"⚠️ Старый говорящий {old_speaker_id} всё ещё в очереди! Пропускаем.")
                # Берем следующего, если есть
                if self.waiting_queues[channel_id]:
                    next_speaker_id = self.waiting_queues[channel_id].pop(0)
                else:
                    next_speaker_id = None

            if next_speaker_id:
                self.current_speakers[channel_id] = next_speaker_id
                self.active_channels[channel_id][next_speaker_id].is_speaking = True

                next_speaker_name = self.active_channels[channel_id][next_speaker_id].username
                logger.info(f"➡️ ТЕПЕРЬ ГОВОРИТ в канале {channel_id}: {next_speaker_name}")

                # Уведомляем всех о новом говорящем
                await self._broadcast_to_channel(channel_id, {
                    "type": MessageType.SPEAKER_CHANGED,
                    "speaker_id": next_speaker_id,
                    "speaker_name": next_speaker_name,
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                })

                # Уведомляем нового говорящего
                await self._send_to_user(channel_id, next_speaker_id, {
                    "type": MessageType.SPEAK_GRANTED,
                    "message": "You can speak now",
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat()
                })

    async def process_audio_chunk(self, ws_user_id: str, channel_id: int, audio_data: bytes):
        """Обработка аудио чанка в реальном времени"""
        if self.current_speakers.get(channel_id) != ws_user_id:
            logger.warning(f"⚠️ Попытка передачи без права: {ws_user_id} в канале {channel_id}")
            return

        # Получаем имя говорящего
        speaker_name = None
        if channel_id in self.active_channels and ws_user_id in self.active_channels[channel_id]:
            speaker_name = self.active_channels[channel_id][ws_user_id].username

        # Если идет запись канала - сохраняем аудио
        await self.recorder.record_audio_chunk(channel_id, audio_data, ws_user_id, speaker_name)

        # Трансляция всем остальным пользователям в канале
        await self._broadcast_audio(channel_id, ws_user_id, audio_data)

    async def _broadcast_audio(self, channel_id: int, sender_id: str, audio_data: bytes):
        """Трансляция аудио всем в канале, кроме отправителя"""
        if channel_id not in self.active_channels:
            return

        tasks = []

        for user_id, user in self.active_channels[channel_id].items():
            if user_id == sender_id:
                continue

            # Проверяем, нужна ли этому пользователю "подготовка" аудио
            if not hasattr(user, 'audio_initialized'):
                user.audio_initialized = False

            if not user.audio_initialized:
                # Отправляем 3 "тихих" пакета для инициализации аудио системы
                silent_packet = bytes([0] * 1024)  # 1KB тишины

                try:
                    # Отправляем подготовительные пакеты
                    for _ in range(3):
                        await user.websocket.send_bytes(silent_packet)

                    user.audio_initialized = True
                    logger.debug(f"Отправлены подготовительные пакеты для {user.username}")
                except Exception as e:
                    logger.error(f"Ошибка отправки подготовительных пакетов {user.username}: {e}")
                    continue

            # Отправляем реальное аудио
            try:
                tasks.append(user.websocket.send_bytes(audio_data))
            except Exception as e:
                logger.error(f"Ошибка отправки аудио {user.username}: {e}")
                asyncio.create_task(self.disconnect_user(user_id, channel_id))

        # Параллельная отправка
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_channel_status(self, channel_id: int) -> Optional[RadioStatus]:
        """Получение текущего статуса канала"""
        async with self._lock:
            if channel_id not in self.active_channels:
                logger.error(f"Канала нет")
                return None

            return RadioStatus(
                channel_id=channel_id,
                current_speaker=self.current_speakers[channel_id],
                current_speaker_name=self.active_channels[channel_id][
                    self.current_speakers[channel_id]].username if self.current_speakers[channel_id] else None,
                waiting_queue=self.waiting_queues[channel_id].copy(),
                waiting_names=[self.active_channels[channel_id][uid].username for uid in
                               self.waiting_queues[channel_id]],
                connected_users=list(self.active_channels[channel_id].keys()),
                connected_usernames=[user.username for user in self.active_channels[channel_id].values()],
                total_connected=len(self.active_channels[channel_id]),
                server_time=datetime.now()
            )

    async def _send_status_to_user(self, channel_id: int, user_id: str):
        """Отправка статуса конкретному пользователю в канале"""
        status = await self.get_channel_status(channel_id)
        if status:
            await self._send_to_user(channel_id, user_id, {
                "type": MessageType.STATUS,
                "status": {
                    "channel_id": status.channel_id,
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

    async def _send_recording_status_to_user(self, channel_id: int, user_id: str):
        """Отправка статуса конкретному пользователю в канале"""
        status =  self.recorder.get_recording_status(channel_id)
        if status:
            await self._send_to_user(channel_id, user_id, {
                "type": MessageType.RECORDING_STATUS,
                "recording_status": status,
            })

    async def _send_to_user(self, channel_id: int, user_id: str, message: Dict):
        """Отправка сообщения конкретному пользователю в канале"""
        if channel_id in self.active_channels and user_id in self.active_channels[channel_id]:
            try:
                await self.active_channels[channel_id][user_id].websocket.send_text(
                    json.dumps(message)
                )
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
                asyncio.create_task(self.disconnect_user(user_id, channel_id))

    async def _broadcast_to_channel(self, channel_id: int, message: Dict):
        """Отправка сообщения всем пользователям в канале"""
        if channel_id not in self.active_channels:
            return

        json_message = json.dumps(message)
        tasks = []

        for user in self.active_channels[channel_id].values():
            try:
                tasks.append(user.websocket.send_text(json_message))
            except Exception as e:
                logger.error(f"Ошибка broadcast пользователю {user.username}: {e}")
                asyncio.create_task(self.disconnect_user(user.id, channel_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _broadcast_excluding(self, channel_id: int, exclude_id: str, message: Dict):
        """Отправка сообщения всем в канале, кроме указанного пользователя"""
        if channel_id not in self.active_channels:
            return

        json_message = json.dumps(message)
        tasks = []

        for user in self.active_channels[channel_id].values():
            if user.id != exclude_id:
                try:
                    tasks.append(user.websocket.send_text(json_message))
                except Exception as e:
                    logger.error(f"Ошибка broadcast пользователю {user.username}: {e}")
                    asyncio.create_task(self.disconnect_user(user.id, channel_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start_recording(self, channel_id: int, speaker_name: str) -> Dict:
        """Начать запись эфира в канале"""
        if channel_id not in self.active_channels:
            return {
                "success": False,
                "message": f"Channel {channel_id} is empty or doesn't exist"
            }

        await self._broadcast_to_channel(channel_id, {
            "type": MessageType.RECORDING_STARTED,
            "channel_id": channel_id,
            "timestamp": datetime.now().isoformat()
        })

        result = await self.recorder.start_recording(channel_id, speaker_name)

        if result["success"]:
            # Уведомляем всех в канале о начале записи
            await self._broadcast_to_channel(channel_id, {
                "type": "recording_started",  # Добавить в MessageType
                "recording_id": result["recording_id"],
                "filename": result["filename"],
                "timestamp": datetime.now().isoformat()
            })

        return result

    async def stop_recording(self, channel_id: int) -> Dict:
        """Остановить запись эфира в канале"""
        result = await self.recorder.stop_recording(channel_id)

        if result["success"]:
            await self._broadcast_to_channel(channel_id, {
                "type": MessageType.RECORDING_STOPPED,
                "channel_id": channel_id,
                "timestamp": datetime.now().isoformat()
            })
            # Уведомляем всех в канале об окончании записи
            await self._broadcast_to_channel(channel_id, {
                "type": "recording_stopped",  # Добавить в MessageType
                "filename": result["filename"],
                "filepath": result.get("filepath"),
                "duration_seconds": result.get("duration_seconds", 0),
                "timestamp": datetime.now().isoformat()
            })

        return result

    async def get_recording_status(self, channel_id: int) -> Dict:
        """Получить статус записи для канала"""
        return self.recorder.get_recording_status(channel_id)

    async def get_recordings_list(self, timezone: str, channel_id: Optional[int] = None) -> List[Dict]:
        """Получить список всех записей"""
        return await self.recorder.get_recordings_list(channel_id, timezone)