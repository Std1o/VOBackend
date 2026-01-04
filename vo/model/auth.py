from pydantic import BaseModel

class BaseUser(BaseModel):
    phone: str
    username: str

class UserCreate(BaseUser):
    password: str

class User(BaseUser):
    id: int

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'

class PrivateUser(BaseUser):
    id: int
    access_token: str
    token_type: str = 'bearer'

    class Config:
        from_attributes = True