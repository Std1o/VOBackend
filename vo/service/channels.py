import logging
from typing import List

from fastapi import Depends
from sqlalchemy.orm import Session

from vo import tables
from vo.database import get_session
from vo.model.channel import Channel, ChannelUsers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChannelsService:
    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    def get_channels(self, user_id: int) -> List[Channel]:
        channels = self.session.query(tables.Channel).join(tables.Participants).filter(
            tables.Channel.id == tables.Participants.channel_id,
            tables.Participants.user_id == user_id
        ).all()
        for channel in channels:
            logger.info(f"Error deleting channel: {channel}")
            channel.participants = self.get_participants(channel.id)
        return channels

    def get_participants(self, channel_id: int) -> List[ChannelUsers]:
        users = self.session.query(
            tables.User.phone, tables.User.username, tables.Participants.user_id,
            tables.Participants.is_moderator, tables.Participants.is_owner
        ).join(tables.Participants).filter(
            tables.Participants.channel_id == channel_id
        ).all()
        return users