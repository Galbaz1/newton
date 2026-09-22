"""Authoritative identity and intake records; originals are never updated in place."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow


def _id() -> str:
    return str(uuid4())


class User(Base):
    """Account owning its company scopes; emails are normalized before insertion."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Session(Base):
    """Expiring login with only the SHA256 digest of its random cookie persisted."""

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Company(Base):
    """Private company scope belonging to exactly one account."""

    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Machine(Base):
    """Machine description and monotonically increasing evidence context version."""

    __tablename__ = "machines"
    __table_args__ = (CheckConstraint("context_version >= 1"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    context_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Source(Base):
    """Immutable original with editable revision/mapping and explicit processing state."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("version >= 1"),
        CheckConstraint("kind IN ('document', 'image', 'timeseries', 'annotation')"),
        CheckConstraint(
            "status IN ('ready', 'needs_mapping', 'needs_text', 'error', 'quarantined')"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    machine_id: Mapped[str | None] = mapped_column(
        ForeignKey("machines.id"), index=True, nullable=True
    )
    data_class: Mapped[str] = mapped_column(String(20), default="original")
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    revision: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[int] = mapped_column(default=1)
    mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Page(Base):
    """One-based extracted page text; image-only pages retain empty text."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("source_id", "number"), CheckConstraint("number >= 1"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
