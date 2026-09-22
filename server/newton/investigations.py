"""Authenticated conversation routes and explicit correction handling."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.db import get_db
from newton.investigation_models import Investigation, Message
from newton.models import Machine, User
from newton.security import current_user, require_company

router = APIRouter()


class InvestigationInput(BaseModel):
    """A new conversation within a machine the user already owns."""

    machine_id: str
    title: str = Field(default="New investigation", min_length=1, max_length=200)


class CorrectionInput(BaseModel):
    """An explicit user correction against a known machine-context version."""

    text: str = Field(min_length=1, max_length=4000)
    expected_context_version: int = Field(ge=1)


def machine_for_user(db: Session, user: User, machine_id: str) -> Machine:
    """Authorize a machine through its owning company or return a uniform 404."""
    machine = db.get(Machine, machine_id, populate_existing=True)
    if machine is None:
        raise HTTPException(404, "Machine not found.")
    require_company(db, user, machine.company_id)
    return machine


def investigation_for_user(db: Session, user: User, identifier: str) -> tuple:
    """Load a conversation and authorize its machine before revealing content."""
    investigation = db.get(Investigation, identifier, populate_existing=True)
    if investigation is None:
        raise HTTPException(404, "Investigation not found.")
    return investigation, machine_for_user(db, user, investigation.machine_id)


def message_json(message: Message, investigation: Investigation, machine: Machine) -> dict:
    """Mark stale answers explicitly without rewriting their original evidence."""
    stale = message.role == "assistant" and (
        message.scope_revision != investigation.scope_revision
        or message.context_version != machine.context_version
    )
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "created_at": message.created_at,
        "scope_revision": message.scope_revision,
        "context_version": message.context_version,
        "status": "superseded" if stale else message.status,
        "model": message.model,
        "evidence": message.evidence,
        "usage": message.usage,
        "warnings": message.warnings,
    }


def investigation_json(row: Investigation) -> dict:
    """Serialize conversation identity without internal request-lock state."""
    return {
        "id": row.id,
        "machine_id": row.machine_id,
        "title": row.title,
        "scope_revision": row.scope_revision,
        "created_at": row.created_at,
    }


@router.post("/investigations")
def create_investigation(
    body: InvestigationInput, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    """Create a conversation for a machine belonging to the signed-in user."""
    machine_for_user(db, user, body.machine_id)
    row = Investigation(machine_id=body.machine_id, title=body.title)
    db.add(row)
    db.commit()
    db.refresh(row)
    return investigation_json(row)


@router.get("/machines/{machine_id}/investigations")
def list_investigations(
    machine_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list:
    """List only conversations from the requested authorized machine."""
    machine_for_user(db, user, machine_id)
    return [
        investigation_json(row)
        for row in db.scalars(
            select(Investigation)
            .where(Investigation.machine_id == machine_id)
            .order_by(Investigation.created_at.desc())
        )
    ]


@router.get("/investigations/{identifier}")
def get_investigation(
    identifier: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    """Read a conversation with answers labeled against the current context."""
    row, machine = investigation_for_user(db, user, identifier)
    messages = db.scalars(
        select(Message)
        .where(Message.investigation_id == row.id)
        .order_by(Message.created_at, Message.id)
    )
    return {
        **investigation_json(row),
        "messages": [message_json(message, row, machine) for message in messages],
    }


@router.post("/investigations/{identifier}/corrections")
def correct_investigation(
    identifier: str,
    body: CorrectionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Preserve a correction and supersede every prior answer in this conversation."""
    row, machine = investigation_for_user(db, user, identifier)
    if body.expected_context_version != machine.context_version:
        raise HTTPException(409, "Machine context changed; refresh before correcting.")
    row = db.scalar(
        select(Investigation)
        .where(Investigation.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row.scope_revision += 1
    row.corrections = [*row.corrections, body.text]
    db.add(
        Message(
            investigation_id=row.id,
            role="user",
            text=f"Correction: {body.text}",
            scope_revision=row.scope_revision,
            context_version=machine.context_version,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    return get_investigation(identifier, db, user)
