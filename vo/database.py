from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .settings import settings
from sqlalchemy import event
from sqlalchemy.engine import Engine

engine = create_engine(settings.database_url, connect_args={'check_same_thread': False})

Session = sessionmaker(engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    session = Session()
    try:
        yield session
    finally:
        session.close()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
