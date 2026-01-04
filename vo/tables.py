import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = sa.Column(sa.Integer, primary_key=True)
    phone = sa.Column(sa.Text, unique=True)
    username = sa.Column(sa.Text)
    password_hash = sa.Column(sa.Text)

class Channel(Base):
    __tablename__ = 'channel'

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    channel_code = sa.Column(sa.String, unique=True)


class Participants(Base):
    __tablename__ = 'participants'

    user_id = sa.Column(sa.Integer, sa.ForeignKey(User.id), primary_key=True)
    course_id = sa.Column(sa.Integer, sa.ForeignKey(Channel.id, ondelete='CASCADE'), primary_key=True)
    is_moderator = sa.Column(sa.Boolean)
    is_owner = sa.Column(sa.Boolean)