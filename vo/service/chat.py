import logging
from datetime import datetime
from typing import List

from fastapi import Depends
from sqlalchemy import select

from vo import tables
from vo.database import Session, get_session
from vo.model.chat import BaseMessage, Message, MessagesResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    async def get_messages(self, channel_id: int) -> dict:
        statement = select(tables.ChatMessage).filter_by(channel_id=channel_id)
        db_messages = self.session.execute(statement).scalars().all()
        messages = []
        images_count = 0
        for msg in db_messages:
            if msg.image_url:
                images_count += 1
            messages.append({
                "id": msg.id,
                "channel_id": msg.channel_id,
                "user_id": msg.user_id,
                "username": msg.username,
                "content": msg.content,
                "image_url": msg.image_url,
                "time": msg.time
            })

        return {"messages": sorted(messages, key=lambda x: datetime.strptime(x["time"], '%d.%m.%Y %H:%M')), "images_count": images_count}

    async def create_message(self, base_message: BaseMessage) -> dict:
        current_time = datetime.now()
        logger.info(base_message.content)
        new_message = tables.ChatMessage(
            channel_id=base_message.channel_id,
            user_id=base_message.user_id,
            username=base_message.username,
            content=base_message.content,
            image_url=base_message.image_url,
            time=str(current_time.strftime('%d.%m.%Y %H:%M'))
        )
        self.session.add(new_message)
        self.session.commit()

        return await self.get_messages(base_message.channel_id)