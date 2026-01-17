from pydantic import BaseModel


class Ticket(BaseModel):
    user_id: int
    username: str
    phone: str
    image_url: str

    class Config:
        from_attributes = True