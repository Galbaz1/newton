"""Authenticated onboarding operations; background work uses persisted company scope."""

import hashlib
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ._schemas import Input
from ._storage import read_upload, remove_original, save_original
from .db import get_db, utcnow
from .models import User
from .onboarding_models import IntakeItem, OnboardingRun
from .onboarding_state import checkpoint, run_json
from .security import current_user, require_company

router = APIRouter(tags=["onboarding"])


class RunInput(Input):
    """Public company locator and explicit original/synthetic intake classification."""

    website: str = Field(default="", max_length=2000)
    data_class: Literal["original", "synthetic", "demo"] = "original"

    @field_validator("website")
    @classmethod
    def public_url(cls, value: str) -> str:
        """Accept only public-looking HTTP(S) locators; research cannot access local URLs."""
        from .company_research import validate_public_url

        value = value.strip()
        if value and not urlsplit(value).scheme:
            value = "https://" + value
        if value:
            validate_public_url(value)
        return value


class Clarification(Input):
    """Owner-supplied assertion retained as a claim, never an original-data edit."""

    question_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=4000)


def require_run(db, user, run_id: str) -> OnboardingRun:
    """Hide unknown/foreign run identifiers behind the same 404 boundary."""
    run = db.get(OnboardingRun, run_id)
    if run is None:
        raise HTTPException(404, "Onboarding run not found")
    require_company(db, user, run.company_id)
    return run


@router.post("/companies/{company_id}/onboarding")
def create_run(
    company_id: str,
    data: RunInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create an empty draft; this operation never silently starts paid inference."""
    require_company(db, user, company_id)
    run = OnboardingRun(company_id=company_id, **data.model_dump())
    db.add(run)
    db.commit()
    return run_json(db, run)


@router.get("/companies/{company_id}/onboarding")
def list_runs(company_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """List only runs belonging to the selected owned company."""
    require_company(db, user, company_id)
    runs = db.scalars(
        select(OnboardingRun)
        .where(OnboardingRun.company_id == company_id)
        .order_by(OnboardingRun.created_at.desc())
    )
    return [run_json(db, run) for run in runs]


@router.get("/onboarding/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Read persisted progress; refreshing the page does not restart the worker."""
    return run_json(db, require_run(db, user, run_id))


@router.post("/onboarding/{run_id}/files")
def upload_file(
    run_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Retain a bounded exact original and deduplicate repeated uploads within this run."""
    run = require_run(db, user, run_id)
    from .onboarding_worker import is_active

    if is_active(run.id):
        raise HTTPException(409, "The current action is still finishing")
    if run.status not in {"draft", "paused", "error"}:
        raise HTTPException(409, "Pause the run before adding sources")
    data, filename, media_type, kind = read_upload(file)
    digest = hashlib.sha256(data).hexdigest()
    old = db.scalar(
        select(IntakeItem).where(IntakeItem.run_id == run.id, IntakeItem.sha256 == digest)
    )
    if old:
        return run_json(db, run)
    storage_path = save_original(data)
    item = IntakeItem(
        run_id=run.id,
        filename=filename,
        media_type=media_type,
        kind=kind,
        sha256=digest,
        storage_path=storage_path,
        data_class=run.data_class,
    )
    try:
        db.add(item)
        checkpoint(
            db,
            run,
            "upload",
            f"Origineel bewaard: {filename}",
            agent_history=[],
            agent_finished=False,
            pending_calls=[],
            indexed_machines=[],
        )
    except IntegrityError:
        db.rollback()
        remove_original(storage_path)
    except Exception:
        db.rollback()
        remove_original(storage_path)
        raise
    return run_json(db, run)


def _start(db, user, run_id, allowed):
    from .onboarding_worker import launch

    run = require_run(db, user, run_id)
    if run.status not in allowed:
        raise HTTPException(409, "This run cannot be started from its current state")
    if not db.scalar(select(IntakeItem.id).where(IntakeItem.run_id == run.id).limit(1)):
        raise HTTPException(422, "Upload at least one source first")
    launch(db, run)
    return run_json(db, run)


@router.post("/onboarding/{run_id}/start")
def start(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Explicitly start the prepared autonomous onboarding run."""
    return _start(db, user, run_id, {"draft"})


@router.post("/onboarding/{run_id}/resume")
def resume(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Resume durable unfinished work without duplicating successful item writes."""
    return _start(db, user, run_id, {"paused", "error", "completed_with_warnings"})


@router.post("/onboarding/{run_id}/pause")
def pause(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Request a pause at the next tool boundary; retain in-flight call accounting."""
    run = require_run(db, user, run_id)
    if run.status != "running":
        raise HTTPException(409, "Only a running run can be paused")
    run.status, run.updated_at = "paused", utcnow()
    checkpoint(db, run, "pause", "Pauze aangevraagd; lopende stap wordt veilig afgerond.")
    return run_json(db, run)


@router.post("/onboarding/{run_id}/answers")
def clarify(
    run_id: str,
    data: Clarification,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Record a clarification separately from model inferences and original observations."""
    run = require_run(db, user, run_id)
    from .onboarding_worker import is_active

    if run.status == "running" or is_active(run.id):
        raise HTTPException(409, "Pause the run and wait for its current action before clarifying")
    questions = [dict(q) for q in run.state.get("pending_questions", [])]
    question = next((q for q in questions if q["id"] == data.question_id), None)
    if question is None:
        raise HTTPException(404, "Clarification not found")
    question["answer"] = data.answer.strip()
    checkpoint(
        db,
        run,
        "clarification",
        "Gebruikersverklaring vastgelegd.",
        pending_questions=questions,
        questions=[],
        agent_history=[],
        agent_finished=False,
        pending_calls=[],
    )
    return run_json(db, run)
