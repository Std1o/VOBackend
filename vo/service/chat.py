from datetime import datetime
from typing import List

from fastapi import Depends
from sqlalchemy import select

from vo import tables
from vo.database import Session, get_session
from vo.model.chat import BaseMessage, Message


class ChatService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    async def get_messages(self, channel_id: int) -> List[Message]:
        statement = select(tables.ChatMessage).filter_by(channel_id=channel_id).order_by("id")
        return self.session.execute(statement).scalars().all()

    async def create_message(self, base_message: BaseMessage) -> List[Message]:
        current_time = datetime.now()
        new_message = tables.ChatMessage(
            channel_id=base_message.channel_id,
            user_id=base_message.user_id,
            username=base_message.username,
            content=base_message.content,
            image_url=base_message.image_url,
            time=str(current_time.strftime('%H:%M'))
        )
        self.session.add(new_message)
        self.session.commit()

        return await self.get_messages(base_message.channel_id)