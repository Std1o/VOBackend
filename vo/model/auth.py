from datetime import date

from pydantic import BaseModel, ConfigDict


class BaseUser(BaseModel):
    phone: str
    username: str

class UserCreate(BaseUser):
    password: str

class User(BaseUser):
    id: int
    premium: date

    class Config:
        from_attributes = True
        json_encoders = {
            date: lambda v: v.isoformat()  # Это решает проблему!
        }

class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'

class PrivateUser(User):
    access_token: str
    token_type: str = 'bearer'

    class Config:
        from_attributes = True
        json_encoders = {
            date: lambda v: v.isoformat()  # Это решает проблему!
        }