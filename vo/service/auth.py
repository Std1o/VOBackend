import sys
from datetime import datetime, timedelta, date

from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.hash import bcrypt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..model.auth import User, UserCreate, PrivateUser
from ..settings import settings
from jose import jwt, JWTError
from .. import tables

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/auth/sign-in')

def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    return AuthService.validate_token(token)


class AuthService:
    @classmethod
    def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
        return bcrypt.verify(plain_password, hashed_password)

    @classmethod
    def hash_password(cls, password: str) -> str:
        return bcrypt.hash(password)

    @classmethod
    def validate_token(cls, token: str) -> User:
        exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Could not validate credentials',
            headers={
                'WWW-Authenticate': 'Bearer'
            }
        )
        try:
            payload = jwt.decode(token, settings.jwt_sercret, algorithms=[settings.jwt_algorithm])
        except JWTError:
            raise exception from None

        user_data = payload.get('user')

        try:
            user = User.parse_obj(user_data)
        except ValidationError:
            raise exception from None
        return user

    @classmethod
    def create_token(cls, user: tables.User) -> str:

        try:
            user_data = User.from_orm(user)
            now = datetime.utcnow()

            # Получаем словарь
            user_dict = user_data.dict()
            # Принудительно преобразуем premium в строку
            if 'premium' in user_dict:
                if isinstance(user_dict['premium'], date):
                    user_dict['premium'] = user_dict['premium'].isoformat()

            payload = {
                'iat': now,
                'nbf': now,
                'exp': now + timedelta(seconds=settings.jwt_expiration),
                'sub': str(user_data.id),
                'user': user_dict
            }
            # Проверяем сериализацию
            import json
            try:
                test_json = json.dumps(payload)
            except Exception as e:
                # Найдем проблемное поле
                for key, value in payload.items():
                    try:
                        json.dumps({key: value})
                    except Exception as e:

                        if key == 'user':
                            for subkey, subvalue in value.items():
                                try:
                                    json.dumps({subkey: subvalue})
                                except Exception as e:
                                    raise
            # Кодируем токен
            token = jwt.encode(payload, settings.jwt_sercret, algorithm=settings.jwt_algorithm)

            return token

        except Exception as e:
            raise

    def __init__(self, session: Session = Depends(get_session)):
        self.session = session

    def get_user_by_phone(self, phone: str) -> tables.User:
        statement = select(tables.User).filter_by(phone=phone)
        return self.session.execute(statement).scalars().first()

    def reg(self, user_data: UserCreate) -> PrivateUser:
        if self.get_user_by_phone(user_data.phone):
            raise HTTPException(status_code=418, detail="User with this phone already exists")
        premium = (datetime.now() - timedelta(days=1)).date()
        user = tables.User(
            phone=user_data.phone,
            username=user_data.username,
            premium=premium,
            password_hash=self.hash_password(user_data.password))
        self.session.add(user)
        self.session.commit()
        token = self.create_token(user)
        created_user = self.session.query(tables.User).filter_by(phone=user.phone).first()
        return PrivateUser(phone=created_user.phone,
                           username=created_user.username,
                           id=created_user.id,
                           premium=premium,
                           access_token=token)

    # Настройка логирования

    def auth(self, phone: str, password: str) -> PrivateUser:
        exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect username or password',
            headers={
                'WWW-Authenticate': 'Bearer'
            }
        )
        user = self.session.query(tables.User).filter_by(phone=phone).first()
        if not user:
            raise exception
        if not self.verify_password(password, user.password_hash):
            raise exception
        token = self.create_token(user)
        user_dict = {
            'phone': user.phone,
            'username': user.username,
            'id': user.id,
            'premium': user.premium.isoformat(),
            'access_token': token,
            'token_type': 'bearer'
        }
        try:
            private_user = PrivateUser(**user_dict)
            return private_user
        except Exception as e:
            raise
