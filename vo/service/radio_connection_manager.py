import asyncio
import logging
import random
import uuid
from datetime import datetime
from typing import Dict, Optional, List
from collections import defaultdict
from sqlalchemy.orm import Session

from vo.model.message_type import MessageType
from vo.model.radio_status import RadioStatus
from vo.model.user import User
from fastapi import WebSocket, Depends
import json

from ..database import get_session
from ..tables import Channel, User as DBUser, Participants

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

    def set_session(self, session: Session):
        """Устанавливаем сессию БД (вызывается при каждом запросе)"""
        self.session = session

    # ========== Методы для работы с каналами ==========

    async def _add_user_to_channel(self, user_id: int, channel_id: int,
                                   is_moderator: bool = False, is_owner: bool = False) -> bool:
        """Добавление пользователя в канал по ID пользователя"""
        # Находим канал
        channel = self.session.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            return False

        # Находим пользователя
        user = self.session.query(DBUser).filter(DBUser.id == user_id).first()
        if not user:
            return False

        # Проверяем, не является ли пользователь уже участником
        existing_participant = self.session.query(Participants).filter(
            Participants.user_id == user_id,
            Participants.channel_id == channel_id
        ).first()

        if existing_participant:
            # Обновляем права, если нужно
            if is_owner:
                existing_participant.is_owner = True
            if is_moderator:
                existing_participant.is_moderator = True
            self.session.commit()
        else:
            # Добавляем как нового участника
            participant = Participants(
                user_id=user_id,
                channel_id=channel_id,
                is_moderator=is_moderator,
                is_owner=is_owner
            )
            self.session.add(participant)
            self.session.commit()

        return True

    async def add_user_to_channel(self, user_id: int, channel_id: int) -> Dict:
        """Добавление пользователя в существующий канал по ID пользователя"""
        success = await self._add_user_to_channel(user_id, channel_id)

        if success:
            user = self.session.query(DBUser).filter(DBUser.id == user_id).first()
            return {
                "success": True,
                "message": f"User {user.username if user else user_id} added to channel {channel_id}"
            }
        else:
            return {
                "success": False,
                "message": f"Failed to add user {user_id} to channel {channel_id}"
            }

    async def remove_user_from_channel(self, user_id: int, channel_id: int) -> Dict:
        """Удаление пользователя из канала по ID пользователя"""
        try:
            # Находим участника
            participant = self.session.query(Participants).filter(
                Participants.user_id == user_id,
                Participants.channel_id == channel_id
            ).first()

            if not participant:
                return {
                    "success": False,
                    "message": f"User {user_id} is not a participant of channel {channel_id}"
                }

            # Если пользователь онлайн в этом канале, отключаем его
            if channel_id in self.active_channels:
                for ws_user_id, user_obj in list(self.active_channels[channel_id].items()):
                    # Находим username по user_id из БД
                    user = self.session.query(DBUser).filter(DBUser.id == user_id).first()
                    if user and user_obj.username == user.username:
                        await self.disconnect_user(ws_user_id, channel_id)
                        break

            # Удаляем из БД
            self.session.delete(participant)
            self.session.commit()

            return {
                "success": True,
                "message": f"User {user_id} removed from channel {channel_id}"
            }

        except Exception as e:
            self.session.rollback()
            logger.error(f"Error removing user from channel: {e}")
            return {
                "success": False,
                "message": f"Error removing user: {str(e)}"
            }

    async def get_channel_info(self, channel_id: int) -> Optional[Dict]:
        """Получение информации о канале"""
        channel = self.session.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            return None

        # Получаем список участников
        participants = self.session.query(Participants).filter(
            Participants.channel_id == channel_id
        ).join(DBUser, Participants.user_id == DBUser.id).all()

        participants_info = []
        for p in participants:
            user = self.session.query(DBUser).filter(DBUser.id == p.user_id).first()
            participants_info.append({
                "user_id": p.user_id,
                "username": user.username if user else "Unknown",
                "is_moderator": p.is_moderator,
                "is_owner": p.is_owner
            })

        return {
            "id": channel.id,
            "name": channel.name,
            "channel_code": channel.channel_code,
            "participants": participants_info,
            "participant_count": len(participants_info),
            "is_active": channel_id in self.active_channels,
            "active_users": len(self.active_channels.get(channel_id, {}))
        }

    async def list_channels(self, include_participants: bool = False) -> List[Dict]:
        """Получение списка всех каналов"""
        channels = self.session.query(Channel).all()

        result = []
        for channel in channels:
            channel_info = {
                "id": channel.id,
                "name": channel.name,
                "channel_code": channel.channel_code,
                "is_active": channel.id in self.active_channels,
                "active_users": len(self.active_channels.get(channel.id, {}))
            }

            if include_participants:
                participants = self.session.query(Participants).filter(
                    Participants.channel_id == channel.id
                ).count()
                channel_info["participant_count"] = participants

            result.append(channel_info)

        return result

    async def delete_channel(self, channel_id: int, requesting_user_id: int) -> Dict:
        """Удаление канала (только владельцем)"""
        try:
            # Находим канал
            channel = self.session.query(Channel).filter(Channel.id == channel_id).first()
            if not channel:
                return {
                    "success": False,
                    "message": f"Channel {channel_id} not found"
                }

            # Проверяем права доступа (только владелец может удалить канал)
            participant = self.session.query(Participants).filter(
                Participants.user_id == requesting_user_id,
                Participants.channel_id == channel_id,
                Participants.is_owner == True
            ).first()

            if not participant:
                return {
                    "success": False,
                    "message": "Only channel owner can delete the channel"
                }

            # Отключаем всех активных пользователей
            if channel_id in self.active_channels:
                user_ids = list(self.active_channels[channel_id].keys())
                for user_id in user_ids:
                    await self.disconnect_user(user_id, channel_id)

            # Удаляем канал (каскадно удалятся и участники)
            self.session.delete(channel)
            self.session.commit()

            # Очищаем данные в памяти
            if channel_id in self.active_channels:
                del self.active_channels[channel_id]
            if channel_id in self.current_speakers:
                del self.current_speakers[channel_id]
            if channel_id in self.waiting_queues:
                del self.waiting_queues[channel_id]

            logger.info(f"🗑️ Удален канал: {channel.name} (ID: {channel_id}) владельцем {requesting_user_id}")

            return {
                "success": True,
                "message": f"Channel {channel.name} deleted successfully"
            }

        except Exception as e:
            self.session.rollback()
            logger.error(f"Error deleting channel: {e}")
            return {
                "success": False,
                "message": f"Error deleting channel: {str(e)}"
            }

    async def get_user_channels(self, user_id: int) -> List[Dict]:
        """Получение списка каналов, в которых состоит пользователь"""
        participants = self.session.query(Participants).filter(
            Participants.user_id == user_id
        ).all()

        channels_info = []
        for p in participants:
            channel = self.session.query(Channel).filter(Channel.id == p.channel_id).first()
            if channel:
                channels_info.append({
                    "id": channel.id,
                    "name": channel.name,
                    "channel_code": channel.channel_code,
                    "is_owner": p.is_owner,
                    "is_moderator": p.is_moderator,
                    "is_active": channel.id in self.active_channels,
                    "active_users": len(self.active_channels.get(channel.id, {}))
                })

        return channels_info

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

    async def request_speak(self, ws_user_id: str, channel_id: int) -> Dict:
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
            if self.current_speakers[channel_id] != ws_user_id:
                # Если пользователь в очереди - удаляем
                if ws_user_id in self.waiting_queues[channel_id]:
                    self.waiting_queues[channel_id].remove(ws_user_id)
                    return {
                        "type": MessageType.SPEAK_RELEASED,
                        "message": "Removed from queue",
                        "channel_id": channel_id,
                        "timestamp": datetime.now().isoformat()
                    }
                return {
                    "type": MessageType.ERROR,
                    "message": "You are not the current speaker",
                    "timestamp": datetime.now().isoformat()
                }

            # Освобождаем право
            self.current_speakers[channel_id] = None
            self.active_channels[channel_id][ws_user_id].is_speaking = False

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
        # Быстрая проверка без блокировки
        if self.current_speakers.get(channel_id) != ws_user_id:
            logger.warning(f"⚠️ Попытка передачи без права: {ws_user_id} в канале {channel_id}")
            return

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