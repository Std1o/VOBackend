from pydantic import BaseModel


class BlackList(BaseModel):
    user_id: int
    channel_id: int