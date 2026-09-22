"""Private metadata projections for the separate local MLflow synchronizer."""

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from .config import settings
from .onboarding_models import IntakeItem

logger = logging.getLogger(__name__)


def project_onboarding(db, run) -> dict:
    """Export measured progress without source text, filenames, keys or user identities.

    Checkpoint events are point observations: equal start/end times deliberately do
    not claim action durations. Detailed provider receipts remain in private storage.
    """
    items = list(db.scalars(select(IntakeItem).where(IntakeItem.run_id == run.id)))
    counts = Counter(item.status for item in items)
    questions = run.state.get("questions", [])
    events = []
    for event in run.state.get("events", []):
        at = round(datetime.fromisoformat(event["at"]).timestamp() * 1000)
        identity = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        events.append(
            {
                "id": identity,
                "name": event["kind"],
                "start_ms": at,
                "end_ms": at,
                "status": "error" if event["kind"] == "error" else "ok",
                "inputs": {"observation": "checkpoint"},
                "outputs": {"kind": event["kind"]},
            }
        )
    state = {
        "completed": "finished",
        "completed_with_warnings": "finished",
        "error": "failed",
        "paused": "paused",
    }.get(run.status, "running")
    return {
        "schema": 1,
        "id": run.id,
        "experiment": "Newton onboarding",
        "name": f"Onboarding {run.id[:8]} · {run.data_class}",
        "status": state,
        "start_ms": round(run.created_at.timestamp() * 1000),
        "end_ms": round(run.updated_at.timestamp() * 1000)
        if state in {"finished", "failed"}
        else None,
        "params": {"data_class": run.data_class, "executor_model": "gemini-3.8-flash"},
        "metrics": {
            "source_count": len(items),
            "ready_sources": counts["ready"],
            "quarantined_sources": counts["quarantined"],
            "error_sources": counts["error"],
            "installations": len(set(run.state.get("assets", {}).values())),
            "ready_questions": sum(q["state"] == "ready" for q in questions),
            "missing_questions": sum(q["state"] == "missing" for q in questions),
            "agent_turns": run.state.get("agent_turns", 0),
            "independent_reviews": len(run.state.get("reviews", [])),
        },
        "tags": {
            "application_status": run.status,
            "privacy": "private_local_only",
            "originals": "immutable",
            "duration_semantics": "checkpoint_events_are_points",
            "cost_scope": "separate_provider_ledger;not_inferred_from_trace_presence",
        },
        "events": events,
    }


def publish_onboarding(db, run) -> None:
    """Atomically publish a local projection; telemetry failure never changes task truth."""
    try:
        directory = settings.data_dir.parent / "observability"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / f"onboarding-{run.id}.json"
        temporary = target.with_suffix(".pending")
        temporary.write_text(json.dumps(project_onboarding(db, run), ensure_ascii=False))
        temporary.chmod(0o600)
        temporary.replace(target)
    except OSError, ValueError:
        logger.exception("Local observability projection failed for run %s", run.id)
