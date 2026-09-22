"""One explicit answering run, with durable admission and stale-result fencing."""

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from weaviate.exceptions import WeaviateBaseError

from newton import answer_documents, budget, providers, retrieval, visual_retrieval
from newton.db import get_db
from newton.evidence import SYSTEM, prompt_text, source_snapshot
from newton.investigation_models import Investigation, Message
from newton.investigations import investigation_for_user, message_json
from newton.models import Machine, User
from newton.onboarding_models import CompanyProfile
from newton.security import current_user, lock_current_session
from newton.series_evidence import MeasurementScope
from newton.series_evidence import series_evidence as _series_evidence

router = APIRouter()


class QuestionInput(BaseModel):
    """One bounded question and the context version visible when it was submitted."""

    text: str = Field(min_length=1, max_length=1500)
    model: str
    measurement: MeasurementScope | None = None
    expected_context_version: int = Field(ge=1)


def _admit(db: Session, user: User, identifier: str, body: QuestionInput) -> tuple:
    row, machine = investigation_for_user(db, user, identifier)
    row = db.scalar(
        select(Investigation)
        .where(Investigation.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    if body.expected_context_version != machine.context_version:
        raise HTTPException(409, "Machine context changed; refresh before asking.")
    if row.active_run_id and row.active_until and row.active_until > now:
        raise HTTPException(409, "This investigation already has an answer in progress.")
    if body.model not in {item["id"] for item in providers.available_models() if item["available"]}:
        raise HTTPException(422, "Selected model is unavailable.")
    run_id = str(uuid4())
    row.active_run_id, row.active_until = run_id, now + timedelta(minutes=10)
    question = Message(
        investigation_id=row.id,
        role="user",
        text=body.text,
        scope_revision=row.scope_revision,
        context_version=machine.context_version,
    )
    db.add(question)
    db.commit()
    return row, machine, run_id, row.scope_revision, machine.context_version


def _history(db: Session, row: Investigation, context_version: int) -> list[dict]:
    messages = list(
        db.scalars(
            select(Message)
            .where(
                Message.investigation_id == row.id,
                Message.scope_revision == row.scope_revision,
                Message.context_version == context_version,
                Message.status == "complete",
            )
            .order_by(Message.created_at.desc())
            .limit(6)
        )
    )
    # Citation IDs are per-answer: remove earlier markers rather than reassign them.
    return [
        {"role": m.role, "text": re.sub(r"\[E[\d, E]+\]", "", m.text)[:3000]}
        for m in reversed(messages)
    ]


def _execute(
    db: Session, row: Investigation, machine, body: QuestionInput, request: Request
) -> tuple:
    run_id, scope, version = row.active_run_id, row.scope_revision, machine.context_version
    sources = source_snapshot(db, machine)
    evidence = retrieval.search(db, machine.company_id, machine.id, body.text, row.active_until)
    visual, pngs = visual_retrieval.search(
        db, machine.company_id, machine.id, body.text, row.active_until
    )
    images = []
    for record, png in zip(visual, pngs, strict=True):
        record["id"] = f"E{len(evidence) + 1}"
        evidence.append(record)
        images.append((record["id"], png))
    next_id = max((int(record["id"][1:]) for record in evidence), default=0) + 1
    images, pdfs, warnings = answer_documents.attach_pdfs(db, machine, evidence, images)
    evidence.extend(_series_evidence(db, machine.id, next_id, body.measurement))
    db.refresh(row)
    db.refresh(machine)
    if (
        row.active_run_id != run_id
        or row.scope_revision != scope
        or machine.context_version != version
    ):
        raise ValueError("Context changed before answering; refresh and ask again.")
    current_user(request, db)
    retrieval.check_deadline(row.active_until)
    prompt = prompt_text(
        machine,
        body.text,
        evidence,
        sources,
        row.corrections,
        _history(db, row, machine.context_version),
        profile.content if (profile := db.get(CompanyProfile, machine.company_id)) else {},
    )
    if warnings:
        prompt += "\nEvidence selection limits: " + json.dumps(warnings, ensure_ascii=False)
    text, usage = providers.answer(SYSTEM, prompt, body.model, tuple(images), tuple(pdfs))
    valid_ids = {item["id"] for item in evidence}
    cited = set(re.findall(r"\bE\d+\b", text))
    if cited - valid_ids:
        warnings.append("The answer contains an unrecognized citation; inspect its evidence.")
    if not evidence:
        warnings.append("No ready source evidence was available for this answer.")
    return text, usage, evidence, warnings


def _accept(
    db: Session,
    request: Request,
    user: User,
    identifier: str,
    run: tuple,
    body: QuestionInput,
    outcome: tuple,
    status: str,
) -> dict:
    """Keep session, scope, lock release and result persistence in one transaction.

    This function exceeds the ordinary size target so the acceptance invariant
    and its row locks remain visible together.
    """
    run_id, scope, version = run
    db.expire_all()
    row, machine = investigation_for_user(db, user, identifier)
    row = db.scalar(
        select(Investigation)
        .where(Investigation.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    machine = db.scalar(
        select(Machine)
        .where(Machine.id == machine.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    auth_error = None
    try:
        lock_current_session(request, db)
    except HTTPException as error:
        auth_error = error
        status = "error"
        outcome = (
            "The session ended before answer delivery; no answer was delivered.",
            outcome[1],
            [],
            ["Sign in again before continuing this investigation."],
        )
    text, usage, evidence, warnings = outcome
    stale = (
        row.active_run_id != run_id
        or row.scope_revision != scope
        or machine.context_version != version
    )
    if stale:
        status = "superseded"
        warnings.append("Context changed during this run; this answer is not current evidence.")
    if row.active_run_id == run_id:
        row.active_run_id, row.active_until = None, None
    message = Message(
        investigation_id=row.id,
        role="assistant",
        text=text,
        usage=usage,
        evidence=evidence,
        warnings=warnings,
        model=body.model,
        status=status,
        scope_revision=scope,
        context_version=version,
    )
    db.add(message)
    db.commit()
    if auth_error is not None:
        raise auth_error
    db.refresh(message)
    return message_json(message, row, machine)


@router.post("/investigations/{identifier}/messages")
def ask(
    identifier: str,
    body: QuestionInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Answer from the current evidence, preserving failures and late corrections.

    The user question is committed before external work. Each call uses the
    central budget and has no automatic retry. A correction or mapping change
    during inference labels the result superseded; revoked sessions receive401.
    """
    row, machine, run_id, scope, version = _admit(db, user, identifier, body)
    status = "complete"
    try:
        outcome = _execute(db, row, machine, body, request)
    except (budget.BudgetExceeded, providers.ProviderError, ValueError) as error:
        outcome = (str(error), None, [], ["No successful answer was produced."])
        status = "error"
    except WeaviateBaseError:
        outcome = (
            "The local retrieval service is unavailable. Original sources are preserved.",
            None,
            [],
            ["No automatic provider retry was made."],
        )
        status = "error"
    except HTTPException as error:
        outcome = (str(error.detail), None, [], ["Evidence could not be read."])
        status = "error"
    return _accept(db, request, user, identifier, (run_id, scope, version), body, outcome, status)
