from typing import List

from pydantic import BaseModel


class BaseMessage(BaseModel):
    channel_id: int
    user_id: int
    username: str
    content: str
    image_url: str = ""

    class Config:
        from_attributes = True

class Message(BaseMessage):
    id: str
    time: str

    class Config:
        from_attributes = True

class MessagesRequest(BaseModel):
    command: str

class MessagesResponse(BaseModel):
    messages: List[Message]

    class Config:
        from_attributes = True