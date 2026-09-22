"""SQLAlchemy seams; sessions roll back uncommitted work when dependencies exit."""

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings


class Base(DeclarativeBase):
    """Shared declarative base, also available to coordinator-owned models."""


class UTCDateTime(TypeDecorator):
    """Preserve timezone-aware UTC timestamps, including in isolated SQLite tests."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Reject naive timestamps and normalize persisted timestamps to UTC."""
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("A timezone-aware timestamp is required")
            return value.astimezone(UTC)
        return None

    def process_result_value(self, value, dialect):
        """Restore UTC awareness lost by SQLite's datetime storage."""
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return None


def _make_engine():
    options = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    result = create_engine(settings.database_url, connect_args=options)
    if result.dialect.name == "sqlite":

        @event.listens_for(result, "connect")
        def _foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    return result


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session]:
    """Yield one request session and close it, rolling back unfinished work."""
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    """Create prototype tables, including any registered coordinator models."""
    from . import models, onboarding_models  # noqa: F401
    from .migrations import migrate_sources

    migrate_sources(engine)

    Base.metadata.create_all(engine)


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)
