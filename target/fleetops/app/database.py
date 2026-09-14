from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from collections.abc import Iterator

from .models.db import Base

DATABASE_URL = "sqlite:///./fleetops.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)

def get_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


def create_schema() -> None:
    Base.metadata.create_all(engine)


