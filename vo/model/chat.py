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
    id: int
    time: str

class MessagesRequest(BaseModel):
    command: str