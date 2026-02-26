import logging
from datetime import datetime
from typing import List, Optional
import pytz
from pytz import timezone, UTC

from fastapi import Depends
from sqlalchemy import select

from vo import tables
from vo.database import Session, get_session
from vo.model.chat import BaseMessage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    async def get_messages(self, channel_id: int, timezone_str: str = 'UTC') -> dict:
        """
        Получение сообщений с учетом часового пояса
        """
        statement = select(tables.ChatMessage).filter_by(channel_id=channel_id)
        db_messages = self.session.execute(statement).scalars().all()
        messages = []
        images_count = 0

        try:
            # Получаем целевой часовой пояс
            target_tz = timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            # Если часовой пояс неизвестен, используем UTC
            target_tz = UTC
            logger.warning(f"Unknown timezone: {timezone_str}, using UTC")

        for msg in db_messages:
            if msg.image_url:
                images_count += 1

            # Конвертируем время в указанный часовой пояс
            msg_time = datetime.strptime(msg.time, '%d.%m.%Y %H:%M')
            # Предполагаем, что в БД время хранится в UTC
            msg_time = UTC.localize(msg_time)
            # Конвертируем в целевой часовой пояс
            msg_time_tz = msg_time.astimezone(target_tz)

            messages.append({
                "id": msg.id,
                "channel_id": msg.channel_id,
                "user_id": msg.user_id,
                "username": msg.username,
                "content": msg.content,
                "image_url": msg.image_url,
                "time": msg_time_tz.strftime('%d.%m.%Y %H:%M')
            })

        # Сортируем по времени
        sorted_messages = sorted(
            messages,
            key=lambda x: datetime.strptime(x["time"], '%d.%m.%Y %H:%M')
        )

        return {
            "messages": sorted_messages,
            "images_count": images_count
        }

    async def create_message(self, base_message: BaseMessage, timezone_str: str = 'UTC') -> dict:
        """
        Создание сообщения с учетом часового пояса
        """
        # Всегда сохраняем в UTC
        current_time = datetime.now(UTC)
        logger.info(f"Creating message in channel {base_message.channel_id}: {base_message.content}")

        new_message = tables.ChatMessage(
            channel_id=base_message.channel_id,
            user_id=base_message.user_id,
            username=base_message.username,
            content=base_message.content,
            image_url=base_message.image_url,
            time=current_time.strftime('%d.%m.%Y %H:%M')
        )
        self.session.add(new_message)
        self.session.commit()
        logger.info(f"Message saved successfully")

        # Возвращаем обновленный список сообщений с учетом часового пояса
        return await self.get_messages(base_message.channel_id, timezone_str)