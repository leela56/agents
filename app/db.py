"""SQLAlchemy 2.0 engine / session bootstrap."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Base for all ORM models."""


_settings = get_settings()

_db_path = Path(_settings.db_path)
_db_path.parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False so APScheduler background threads can share the engine.
engine = create_engine(
    f"sqlite:///{_db_path.as_posix()}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Create all tables. Import models here to register mappers."""
    from . import models  # noqa: F401 - register tables on Base.metadata

    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """Context manager yielding a session and committing on success."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
