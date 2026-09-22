"""One local background onboarding worker with durable SQL checkpoints and pause."""

import threading
import traceback

from fastapi import HTTPException
from sqlalchemy import select

from . import company_research, documents, intake_annotations, intake_profile, onboarding_review
from ._storage import read_original
from .config import settings
from .db import SessionLocal
from .models import Company
from .onboarding_agent import run_agent
from .onboarding_index import index_sources
from .onboarding_models import CompanyProfile, IntakeItem, OnboardingRun
from .onboarding_state import checkpoint

_lock = threading.Lock()
_active: set[str] = set()


class Paused(Exception):
    """Internal control transfer at an acknowledged durable action boundary."""


def check_running(db, run) -> None:
    """Observe owner pause requests before the next action or model admission."""
    db.refresh(run)
    if run.status != "running":
        raise Paused()


def is_active(identifier: str) -> bool:
    """Return whether this process is still finishing the run's current action."""
    with _lock:
        return identifier in _active


def recover(db) -> None:
    """Pause interrupted runs on startup; never automatically replay a paid call."""
    for run in db.scalars(select(OnboardingRun).where(OnboardingRun.status == "running")):
        run.status = "paused"
        checkpoint(
            db, run, "recovery", "Server herstart; voortgang bewaard. Hervatten is beschikbaar."
        )


def launch(db, run) -> None:
    """Admit one worker and commit its running state before starting the thread.

    Args:
        db: Authorized API request session.
        run: Run whose company ownership was already checked.

    Raises:
        HTTPException: Another onboarding action is still running locally.
    """
    with _lock:
        if _active:
            raise HTTPException(
                409, "An onboarding action is still finishing; retry after its checkpoint"
            )
        _active.add(run.id)
        try:
            run.status = "running"
            checkpoint(db, run, "start", "Onboarding gestart of hervat.")
            threading.Thread(
                target=_work, args=(run.id,), daemon=True, name=f"onboarding-{run.id}"
            ).start()
        except Exception:
            _active.discard(run.id)
            raise


def _profile(db, run) -> None:
    items = list(db.scalars(select(IntakeItem).where(IntakeItem.run_id == run.id)))
    for item in items:
        check_running(db, run)
        if item.profile or item.status == "error":
            continue
        run.stage = f"Bron controleren: {item.filename}"
        checkpoint(db, run, "profile", run.stage)
        try:
            data = read_original(item)
            if item.kind == "timeseries":
                profile = intake_profile.profile_csv(data)
            elif item.kind == "annotation":
                profile = intake_annotations.parse_annotations(data)
            else:
                status, profile, pages = documents.extract_document(data, item.media_type)
                if status == "error":
                    raise ValueError(profile["error"])
                profile["page_samples"] = [
                    {"page": i + 1, "text": text[:1600]} for i, text in enumerate(pages[:3])
                ]
            item.profile, item.findings, item.status = (
                profile,
                profile.get("findings", []),
                "profiled",
            )
        except (ValueError, HTTPException) as error:
            item.status = "error"
            item.findings = [
                {"code": "profile_error", "severity": "error", "message": str(error)[:2000]}
            ]
        checkpoint(db, run, "profile", f"{item.filename}: {item.status}")


def _research(db, run) -> None:
    if run.state.get("research_complete"):
        return
    check_running(db, run)
    run.stage = "Bedrijf onderzoeken"
    checkpoint(db, run, "research", "Openbare bedrijfsinformatie onderzoeken.")
    company = db.get(Company, run.company_id)
    profile = company_research.research(run.id, company.name, run.website)
    row = db.get(CompanyProfile, company.id)
    if row is None:
        row = CompanyProfile(company_id=company.id)
        db.add(row)
    row.website, row.content = run.website, profile
    checkpoint(
        db, run, "research", "Bedrijfsprofiel met bronnen vastgelegd.", research_complete=True
    )


def _work(identifier: str) -> None:
    try:
        with SessionLocal() as db:
            run = db.get(OnboardingRun, identifier)
            try:
                _research(db, run)
                _profile(db, run)
                check_running(db, run)
                run.stage = "Bronnen begrijpen en voorbereiden"
                checkpoint(db, run, "stage", run.stage)
                run_agent(db, run, check_running)
                check_running(db, run)
                onboarding_review.verify(db, run, check_running)
                check_running(db, run)
                index_sources(db, run, check_running)
                check_running(db, run)
                items = list(db.scalars(select(IntakeItem).where(IntakeItem.run_id == run.id)))
                warnings = any(i.status in {"error", "quarantined"} or i.findings for i in items)
                run.status = (
                    "completed_with_warnings"
                    if warnings or run.state.get("pending_questions")
                    else "completed"
                )
                run.stage = "Afgerond met zichtbare uitzonderingen" if warnings else "Afgerond"
                checkpoint(db, run, "complete", run.stage)
            except Paused:
                checkpoint(db, run, "paused", "Gepauzeerd op een opgeslagen actiegrens.")
            except Exception as error:
                db.rollback()
                run = db.get(OnboardingRun, identifier, populate_existing=True)
                run.status, run.stage = "error", "Controle vereist"
                error_summary = (
                    str(error)[:3000]
                    if isinstance(error, (ValueError, HTTPException))
                    else "Verwerking onderbroken; originelen en checkpoints zijn behouden."
                )
                path = settings.data_dir / "onboarding" / identifier
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                (path / "worker-error.txt").write_text(traceback.format_exc())
                checkpoint(db, run, "error", error_summary)
    finally:
        with _lock:
            _active.discard(identifier)
