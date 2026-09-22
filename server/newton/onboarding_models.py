"""Durable owner-scoped onboarding progress and immutable intake identities."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow
from .models import _id


class CompanyProfile(Base):
    """Source-backed research, separate from owner-entered company description."""

    __tablename__ = "company_profiles"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    website: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OnboardingRun(Base):
    """Checkpointed local agent run; model output never grants access authority."""

    __tablename__ = "onboarding_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    website: Mapped[str] = mapped_column(Text, default="")
    data_class: Mapped[str] = mapped_column(String(20), default="original")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    stage: Mapped[str] = mapped_column(String(80), default="Files")
    summary: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class IntakeItem(Base):
    """Private original, profile and materialization outcome for one run input."""

    __tablename__ = "intake_items"
    __table_args__ = (UniqueConstraint("run_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("onboarding_runs.id"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    data_class: Mapped[str] = mapped_column(String(20), default="original")
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    machine_id: Mapped[str | None] = mapped_column(ForeignKey("machines.id"), nullable=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
