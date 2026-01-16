import logging
import random
from typing import List, cast

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from vo import tables, constants
from vo.database import get_session
from vo.model.black_list import BlackList
from vo.model.channel import Channel, ChannelUsers, Participants, BaseChannel, ChannelCreate

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_channel_code() -> str:
    seq = "abcdefghijklmnopqrstuvwxyz0123456789"
    code = ''
    for i in range(0, 6):
        code += random.choice(seq)
    return code.upper()


class ChannelsService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    def check_accessibility(self, user_id, channel_id: int):
        participant = self.get_participant(user_id, channel_id)
        if not participant.is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=constants.ACCESS_ERROR)

    async def create(self, user_id: int, channel_data: BaseChannel) -> Channel:
        new_channel = tables.Channel(name=channel_data.name, channel_code=generate_channel_code())
        '''The probability that the code is already occupied is extremely small, 
        but if this happens, we generate a new code'''
        if self.get_channel_by_code(new_channel.channel_code):
            new_channel.channel_code = generate_channel_code()
        self.session.add(new_channel)
        self.session.commit()

        participant = tables.Participants(
            user_id=user_id,
            channel_id=new_channel.id,
            is_moderator=True,
            is_owner=True
        )
        self.session.add(participant)
        self.session.commit()
        logger.info(f"Created channel: {new_channel.id}")
        channel = Channel(name=new_channel.name, id=new_channel.id, channel_code=new_channel.channel_code,
                          participants=self.get_participants(new_channel.id))
        return channel

    async def get_black_list(self, channel_id: int) -> List[BlackList]:
        statement = select(tables.BlackList).filter_by(channel_id=channel_id)
        return self.session.execute(statement).scalars().all()

    async def add_to_black_list(self, participant_id: int, channel_id: int) -> List[BlackList]:
        participant = tables.BlackList(
            user_id=participant_id,
            channel_id=channel_id,
        )
        self.session.add(participant)
        self.session.commit()
        return await self.get_black_list(channel_id)

    async def get_channels(self, user_id: int) -> List[Channel]:
        channels = self.session.query(tables.Channel).join(tables.Participants).filter(
            tables.Channel.id == tables.Participants.channel_id,
            tables.Participants.user_id == user_id
        ).all()
        for channel in channels:
            logger.info(f"Error deleting channel: {channel}")
            channel.participants = self.get_participants(channel.id)
            channel.black_list = await self.get_black_list(channel.id)
        return channels

    async def join(self, user_id: int, channel_code: str) -> Channel:
        course = self.get_channel_by_code(channel_code)
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        channel_id = course.id
        if user_id in self.get_participants_ids(channel_id):
            raise HTTPException(status_code=418, detail="You have already joined the channel")
        participants = Participants(user_id=user_id, channel_id=channel_id)
        self.session.add(tables.Participants(**participants.dict()))
        self.session.commit()
        return await self._get(user_id, channel_id)

    def get_participants(self, channel_id: int) -> List[ChannelUsers]:
        users = self.session.query(
            tables.User.phone, tables.User.username, tables.Participants.user_id,
            tables.Participants.is_moderator, tables.Participants.is_owner
        ).join(tables.Participants).filter(
            tables.Participants.channel_id == channel_id
        ).all()

        # Преобразуем Row объекты в словари
        result = []
        for user in users:
            # Row._asdict() преобразует Row в словарь
            user_dict = user._asdict()
            result.append(ChannelUsers(**user_dict))

        return result

    def get_channel_by_code(self, channel_code: str) -> tables.Channel:
        statement = select(tables.Channel).filter_by(channel_code=channel_code)
        return self.session.execute(statement).scalars().first()

    def get_participants_ids(self, channel_id: int) -> List[int]:
        statement = select(tables.Participants.user_id).filter_by(channel_id=channel_id)
        return self.session.execute(statement).scalars().all()

    async def _get(self, user_id: int, channel_id: int) -> Channel:
        channel = self.session.query(tables.Channel).join(tables.Participants).filter(
            tables.Channel.id == channel_id,
            tables.Participants.user_id == user_id
        ).first()
        if not channel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        channel.participants = self.get_participants(channel.id)
        channel.black_list = await self.get_black_list(channel.id)
        return channel

    def get_participant(self, participant_id: int, channel_id) -> tables.Participants:
        statement = select(tables.Participants).filter_by(user_id=participant_id, channel_id=channel_id)
        return self.session.execute(statement).scalars().first()

    async def delete_participant(self, user_id, participant_id: int, channel_id: int):
        self.check_accessibility(user_id, channel_id)
        participant = self.get_participant(participant_id, channel_id)
        self.session.delete(participant)
        self.session.commit()
        return self.get_participants(channel_id)

    def get_black_list_item(self, participant_id: int, channel_id) -> tables.BlackList:
        statement = select(tables.BlackList).filter_by(user_id=participant_id, channel_id=channel_id)
        return self.session.execute(statement).scalars().first()

    async def remove_from_black_list(self, user_id, participant_id: int, channel_id: int):
        self.check_accessibility(user_id, channel_id)
        black_list = self.get_black_list_item(participant_id, channel_id)
        logger.info(f"Created channel: {black_list}")
        self.session.delete(black_list)
        self.session.commit()
        return await self.get_black_list(channel_id)
