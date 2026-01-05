from typing import List, Optional
from pydantic import BaseModel
import random
from .auth import User, BaseUser


class BaseChannel(BaseModel):
    name: str


class ChannelUsers(BaseUser):
    user_id: int
    is_moderator: bool
    is_owner: bool


class Channel(BaseChannel):
    id: int
    channel_code: str
    participants: List[ChannelUsers]

    class Config:
        from_attributes = True


class Participants(BaseModel):
    user_id: int
    channel_id: int
    is_moderator: bool = False
    is_owner: bool = False
