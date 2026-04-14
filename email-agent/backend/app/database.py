"""Async SQLAlchemy database setup with SQLite.

Uses async engine for non-blocking I/O and proper connection lifecycle management.
"""

from __future__ import annotations

import datetime
from enum import Enum

import structlog
from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Base Model
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class EmailCategory(str, Enum):
    URGENT = "urgent"
    ACTION_REQUIRED = "action_required"
    INFORMATIONAL = "informational"
    SPAM = "spam"
    UNCATEGORIZED = "uncategorized"


class DraftTone(str, Enum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    BRIEF = "brief"


# ---------------------------------------------------------------------------
# Email Table
# ---------------------------------------------------------------------------
class EmailRecord(Base):
    """Stored email with AI analysis results."""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gmail_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="(no subject)")
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(200))
    recipients: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    # AI analysis results
    category: Mapped[str] = mapped_column(
        String(50), default=EmailCategory.UNCATEGORIZED, index=True
    )
    category_confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[str | None] = mapped_column(Text)  # JSON array
    action_items: Mapped[str | None] = mapped_column(Text)  # JSON array
    sentiment: Mapped[str | None] = mapped_column(String(20))
    draft_reply: Mapped[str | None] = mapped_column(Text)
    draft_tone: Mapped[str | None] = mapped_column(String(20))

    # Metadata
    is_processed: Mapped[bool] = mapped_column(default=False, index=True)
    processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<EmailRecord(id={self.id}, subject='{self.subject[:30]}...', category={self.category})>"


# ---------------------------------------------------------------------------
# Database Engine & Session
# ---------------------------------------------------------------------------
_engine = None
_session_factory = None


async def init_database() -> None:
    """Initialize the database engine and create tables."""
    global _engine, _session_factory

    settings = get_settings()

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.is_development,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("database_initialized", url=settings.database_url)


async def close_database() -> None:
    """Close database connections."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("database_closed")


async def get_db_session() -> AsyncSession:
    """Get a database session (dependency injection)."""
    if _session_factory is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
