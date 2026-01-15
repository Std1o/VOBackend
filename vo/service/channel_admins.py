from typing import List

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from vo import constants, tables
from vo.database import get_session
from vo.model.channel import ChannelUsers


class ChannelAdminsService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    def check_accessibility(self, user_id, channel_id: int):
        participant = self.get_participant(user_id, channel_id)
        if not participant.is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=constants.ACCESS_ERROR)

    def get_participant(self, admin_id: int, channel_id) -> tables.Participants:
        statement = select(tables.Participants).filter_by(user_id=admin_id, channel_id=channel_id)
        return self.session.execute(statement).scalars().first()

    # main functions
    async def add_admin(self, user_id: int, admin_id: int, channel_id: int):
        self.check_accessibility(user_id, channel_id)
        participant = self.get_participant(admin_id, channel_id)
        if participant.is_moderator:
            raise HTTPException(status_code=418, detail="The user is already moderator")
        participant.is_moderator = True
        self.session.commit()
        return self.get_participants(channel_id)

    async def delete_admin(self, user_id: int, admin_id: int, channel_id: int):
        self.check_accessibility(user_id, channel_id)
        participant = self.get_participant(admin_id, channel_id)
        if not participant.is_moderator:
            raise HTTPException(status_code=418, detail="The user is not admin")
        participant.is_moderator = False
        self.session.commit()
        return self.get_participants(channel_id)

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
