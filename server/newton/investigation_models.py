"""Persisted conversations and the scope needed to reject stale answers."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from newton.db import Base, UTCDateTime


class Investigation(Base):
    """A machine conversation with one bounded active answering run."""

    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scope_revision: Mapped[int] = mapped_column(Integer, default=1)
    corrections: Mapped[list] = mapped_column(JSON, default=list)
    active_run_id: Mapped[str | None] = mapped_column(String(36), default=None)
    active_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))


class Message(Base):
    """An answer's immutable evidence snapshot and originating scope/version."""

    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    scope_revision: Mapped[int] = mapped_column(Integer)
    context_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="complete")
    model: Mapped[str | None] = mapped_column(String(80), default=None)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict | None] = mapped_column(JSON, default=None)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=lambda: datetime.now(UTC))
