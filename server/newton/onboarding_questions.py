"""Validate generated starter questions against actual source availability."""

from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field
from sqlalchemy import select

from ._schemas import Input
from ._storage import read_original
from .measurements import extract_series
from .models import Source
from .onboarding_models import IntakeItem
from .onboarding_state import checkpoint
from .series_evidence import MeasurementScope


class Starter(Input):
    text: str = Field(min_length=1, max_length=1500)
    origin: Literal["role", "source"]
    state: Literal["ready", "missing"]
    object_ref: str | None
    source_ids: list[str] = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=1500)
    capability: Literal["document_lookup", "measurement_summary", "missing"] = "document_lookup"
    measurement: MeasurementScope | None = None


class Pending(Input):
    question: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=1500)
    source_ids: list[str] = Field(max_length=10)


class Finish(Input):
    """Separate role-driven needs, source-supported questions and blocking unknowns."""

    summary: str = Field(min_length=1, max_length=4000)
    questions: list[Starter] = Field(min_length=1, max_length=40)
    pending_questions: list[Pending] = Field(max_length=15)


def _capability(question, selected, available: bool) -> tuple[bool, str]:
    """Bind ready numerical questions to a calculation that actually executes."""
    if not available or question.capability == "missing":
        return False, question.text
    if question.capability == "document_lookup":
        return any(source.kind in {"document", "image"} for source in selected), question.text
    scope = question.measurement
    source = next((s for s in selected if scope and s.id == scope.source_id), None)
    if source is None or source.kind != "timeseries" or not source.mapping:
        raise ValueError("A measurement question requires an explicit selected source and channel")
    channel = next(
        (c for c in source.metadata_json.get("channels", []) if c["column"] == scope.channel), None
    )
    if not channel:
        raise ValueError("Starter question channel has not been established")
    mapping = {**source.mapping, "value_column": scope.channel, "unit": channel["unit"]}
    extract_series(read_original(source), source.id, mapping, scope.start, scope.end)
    period = (
        f"van {scope.start or 'het begin'} tot en met {scope.end or 'het einde'}"
        if scope.start or scope.end
        else "over het hele bestand"
    )
    # Model prose cannot promise unsupported label durations, thresholds or diagnoses.
    return True, (
        f"Wat zijn minimum, maximum, gemiddelde en aantal metingen van {scope.channel} "
        f"{period}? Benoem de vastgestelde eenheid en tijdbasis."
    )


def finish(db, run, args: Finish) -> dict:
    """Downgrade unsupported questions; a model cannot declare unready evidence ready."""
    items = list(db.scalars(select(IntakeItem).where(IntakeItem.run_id == run.id)))
    if any(not item.source_id and item.status != "error" for item in items):
        raise ValueError("Every intake item must be materialized or explicitly quarantined first")
    if any(
        item.kind == "image"
        and item.status != "error"
        and not item.profile.get("visual_observation")
        for item in items
    ):
        raise ValueError("Inspect every image before finishing, including quarantined images")
    sources = {
        s.id: s for s in db.scalars(select(Source).where(Source.company_id == run.company_id))
    }
    questions = []
    for question in args.questions:
        machine_id = run.state.get("assets", {}).get(question.object_ref)
        selected = [sources.get(sid) for sid in question.source_ids]
        if any(source is None for source in selected):
            replacements = {
                item.id: item.source_id
                for item in items
                if item.id in question.source_ids and item.source_id
            }
            if replacements:
                raise ValueError(
                    f"Use materialized source_id, not intake item_id. Corrections: {replacements}"
                )
            raise ValueError("Question refers to a source outside this company")
        available = bool(machine_id and selected) and all(
            s.status in {"ready", "needs_text"}
            and s.machine_id in {None, machine_id}
            and s.data_class in {"original", "derived"}
            for s in selected
        )
        available, text = _capability(question, selected, available)
        record = question.model_dump(exclude={"object_ref"})
        record["text"] = text
        if record["state"] == "ready" and not available:
            record.update(
                state="missing", reason="Benodigde bron of toepasselijkheid is nog niet bevestigd."
            )
        questions.append(
            {
                **record,
                "id": str(uuid5(NAMESPACE_URL, f"{run.id}:starter:{question.model_dump_json()}")),
                "machine_id": machine_id,
            }
        )
    pending = []
    for value in args.pending_questions:
        if any(sid not in sources for sid in value.source_ids):
            raise ValueError("Clarification refers to a source outside this company")
        identifier = str(uuid5(NAMESPACE_URL, f"{run.id}:pending:{value.model_dump_json()}"))
        old = next((q for q in run.state.get("pending_questions", []) if q["id"] == identifier), {})
        pending.append({**old, "id": identifier, **value.model_dump()})
    run.summary = args.summary
    checkpoint(
        db,
        run,
        "questions",
        "Startvragen en ontbrekende informatie vastgelegd.",
        questions=questions,
        pending_questions=pending,
        agent_finished=True,
    )
    return {"finished": True, "ready_questions": sum(q["state"] == "ready" for q in questions)}
