import uuid

import sqlalchemy as sa
from sqlalchemy import DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = sa.Column(sa.Integer, primary_key=True)
    phone = sa.Column(sa.Text, unique=True)
    username = sa.Column(sa.Text)
    password_hash = sa.Column(sa.Text)
    premium = sa.Column(sa.Date)

class Channel(Base):
    __tablename__ = 'channel'

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    channel_code = sa.Column(sa.String, unique=True)


class Participants(Base):
    __tablename__ = 'participants'

    user_id = sa.Column(sa.Integer, sa.ForeignKey(User.id), primary_key=True)
    channel_id = sa.Column(sa.Integer, sa.ForeignKey(Channel.id, ondelete='CASCADE'), primary_key=True)
    is_moderator = sa.Column(sa.Boolean)
    is_owner = sa.Column(sa.Boolean)

class BlackList(Base):
    __tablename__ = 'black_list'

    user_id = sa.Column(sa.Integer, sa.ForeignKey(User.id), primary_key=True)
    channel_id = sa.Column(sa.Integer, sa.ForeignKey(Channel.id, ondelete='CASCADE'), primary_key=True)

class ChatMessage(Base):
    __tablename__ = "chat"

    id = sa.Column(sa.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = sa.Column(sa.String, nullable=False, index=True)
    user_id = sa.Column(sa.Integer, nullable=False)
    username = sa.Column(sa.String, nullable=False)
    content = sa.Column(sa.Text, nullable=False)
    image_url = sa.Column(sa.String)
    time = sa.Column(sa.String)

class Tickets(Base):
    __tablename__ = 'tickets'

    user_id = sa.Column(sa.Integer, sa.ForeignKey(User.id), primary_key=True)
    username = sa.Column(sa.String, nullable=False)
    phone = sa.Column(sa.Text)
    image_url = sa.Column(sa.String)