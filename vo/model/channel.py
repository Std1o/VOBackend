from typing import List, Optional
from pydantic import BaseModel
import random
from .auth import User, BaseUser
from .black_list import BlackList


class BaseChannel(BaseModel):
    name: str


class ChannelUsers(BaseUser):
    user_id: int
    is_moderator: bool
    is_owner: bool


class ChannelCreate(BaseChannel):
    channel_code: str


class Channel(BaseChannel):
    id: int
    channel_code: str
    participants: List[ChannelUsers]
    black_list: List[BlackList]

    class Config:
        from_attributes = True


class Participants(BaseModel):
    user_id: int
    channel_id: int
    is_moderator: bool = False
    is_owner: bool = False
