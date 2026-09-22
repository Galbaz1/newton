"""Independent source-qualified verification; only Python applies containment."""

import hashlib
import json
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from . import onboarding_review_provider
from ._schemas import Input
from .models import Source
from .onboarding_models import IntakeItem
from .onboarding_review_evidence import source_packet
from .onboarding_state import checkpoint
from .source_scope import bump_source_context


class Finding(Input):
    """A bounded concern, never a command or permission to alter original data."""

    target_id: str
    category: Literal[
        "identity", "chronology", "unit", "unsupported_claim", "unsupported_capability"
    ]
    severity: Literal["ordinary", "critical"]
    reason: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    conflict: bool
    channels: list[str] = Field(default_factory=list, max_length=30)


class Review(Input):
    summary: str = Field(min_length=1, max_length=1500)
    findings: list[Finding] = Field(max_length=30)


def packet_for_run(db, run) -> dict:
    """Include new intake and existing company sources used by this run's questions.

    Literal page samples come from authoritative SQL pages. A later batch may use
    an earlier report, but no dangling or foreign reference can reach the reviewer.
    """
    profiles = {
        item.source_id: item.profile
        for item in db.scalars(select(IntakeItem).where(IntakeItem.run_id == run.id))
        if item.source_id
    }
    current_sources = set(profiles)
    for question in [*run.state.get("questions", []), *run.state.get("pending_questions", [])]:
        for source_id in question["source_ids"]:
            profiles.setdefault(source_id, None)
    sources = []
    for source_id, profile in profiles.items():
        source = db.get(Source, source_id)
        if source is None or source.company_id != run.company_id:
            raise ValueError("Review source is missing or outside this company")
        if profile is None:
            profile = source.metadata_json.get("profile", {})
        entry = source_packet(db, source, profile)
        entry["context_only"] = source_id not in current_sources
        sources.append(entry)
    return {
        "sources": sources,
        "questions": run.state.get("questions", []),
        "pending_questions": run.state.get("pending_questions", []),
    }


def validate_review(value: dict, packet: dict) -> Review:
    """Reject invented identities and contradictory escalation labels before any write."""
    review = Review.model_validate(value)
    sources = {s["id"] for s in packet["sources"]}
    questions = {q["id"]: q for q in packet["questions"]}
    targets = sources | questions.keys()
    for finding in review.findings:
        if finding.target_id not in targets or not set(finding.evidence_ids) <= sources:
            raise ValueError("Verifier referred to evidence outside its authorized packet")
        if finding.conflict and len(set(finding.evidence_ids)) < 2:
            raise ValueError("A verifier conflict requires at least two distinct source references")
        if finding.category == "unit":
            linked = {finding.target_id}
            if finding.target_id in questions:
                linked = set(questions[finding.target_id]["source_ids"]) & set(finding.evidence_ids)
            columns = {
                c["column"]
                for s in packet["sources"]
                if s["id"] in linked
                for c in s.get("channels", [])
            }
            if not finding.channels or not set(finding.channels) <= columns:
                raise ValueError("Unit findings require exact channels from the target's sources")
    return review


def critical_findings(review: Review, packet: dict) -> list[Finding]:
    """Escalate only difficult multi-source conflicts affecting currently usable results."""
    ready = {s["id"] for s in packet["sources"] if s["status"] in {"ready", "needs_text"}}
    ready |= {q["id"] for q in packet["questions"] if q["state"] == "ready"}
    return [
        f
        for f in review.findings
        if f.severity == "critical" and f.conflict and f.target_id in ready
    ]


def _withhold_unit(source, finding) -> bool:
    channels = []
    changed = False
    for original in source.metadata_json.get("channels", []):
        channel = dict(original)
        if channel["column"] in finding.channels and channel["unit"] != "unknown":
            changed = True
            channel.update(
                unit="unknown",
                unit_evidence=finding.reason,
                unit_support=None,
                prior_unit_assertion=original,
            )
        channels.append(channel)
    if not changed:
        return False
    source.metadata_json = {
        **source.metadata_json,
        "channels": channels,
        "independent_review": finding.model_dump(),
    }
    if source.mapping and source.mapping["value_column"] in finding.channels:
        source.mapping = {**source.mapping, "unit": "unknown"}
    source.version += 1
    return True


def _contain(db, run, review: Review) -> None:
    questions = [dict(q) for q in run.state.get("questions", [])]
    affected = set()
    current_sources = set(
        db.scalars(select(IntakeItem.source_id).where(IntakeItem.run_id == run.id))
    )
    for finding in review.findings:
        source = db.get(Source, finding.target_id)
        if source and source.id not in current_sources:
            # Earlier batches are evidence only; contain dependent new questions instead.
            affected.add(source.id)
            source = None
        if source and source.status in {"ready", "needs_text"}:
            if finding.category == "unit":
                if _withhold_unit(source, finding):
                    bump_source_context(db, source)
                continue
            source.status = "quarantined"
            source.metadata_json = {
                **source.metadata_json,
                "independent_review": finding.model_dump(),
            }
            for item in db.scalars(
                select(IntakeItem).where(
                    IntakeItem.run_id == run.id, IntakeItem.source_id == source.id
                )
            ):
                item.status = "quarantined"
                item.findings = [
                    *item.findings,
                    {
                        "code": "independent_review",
                        "severity": "warning",
                        "message": finding.reason,
                    },
                ]
            affected.add(source.id)
            bump_source_context(db, source)
        for question in questions:
            if question["id"] == finding.target_id:
                question.update(state="missing", reason=finding.reason)
    for question in questions:
        if affected.intersection(question["source_ids"]):
            question.update(
                state="missing", reason="Brongebruik niet bevestigd na onafhankelijke controle."
            )
    run.state = {**run.state, "questions": questions}


def _escalate(db, run, packet, review, records, pending, check_running):
    """Resolve only the preserved critical targets and retain the paid review on pause."""
    critical = critical_findings(review, packet)
    if critical:
        check_running(db, run)
        critical_packet = {**packet, "critical_conflicts": [f.model_dump() for f in critical]}
        targets = {f.target_id for f in critical}
        second_record = pending.get("escalation")
        if second_record is None:
            raw, usage = onboarding_review_provider.request(
                run.id, critical_packet, escalation=True
            )
            second = validate_review(raw, packet)
            if any(f.target_id not in targets for f in second.findings):
                raise ValueError("Astra review exceeded its critical target scope")
            second_record = {"review": second.model_dump(), "usage": usage}
            pending = {**pending, "escalation": second_record}
            checkpoint(
                db,
                run,
                "verification",
                "Cruciale Astra-controle opgeslagen.",
                review_pending=pending,
            )
        second = validate_review(second_record["review"], packet)
        review.findings = [
            f for f in review.findings if f.target_id not in targets
        ] + second.findings
        records.append(
            {**second.model_dump(), **second_record["usage"], "role": "critical_verifier"}
        )
    return review, records


def verify(db, run, check_running) -> None:
    """Run Sol once per final packet; escalate only a concrete critical conflict to Astra.

    Reviews can withhold unsupported unit assertions, contain evidence or disable a
    starter question. Original bytes, values, timestamps and asset identities stay intact.
    Provider failures remain visible and resumable, with their receipts and costs retained.
    """
    packet = packet_for_run(db, run)
    fingerprint = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
    if run.state.get("review_input_sha256") == fingerprint:
        return
    check_running(db, run)
    run.stage = "Onafhankelijke controle door Sol"
    checkpoint(db, run, "verification", run.stage)
    pending = run.state.get("review_pending", {})
    if pending.get("input_sha256") != fingerprint:
        raw, usage = onboarding_review_provider.request(run.id, packet)
        review = validate_review(raw, packet)
        pending = {"input_sha256": fingerprint, "review": review.model_dump(), "usage": usage}
        checkpoint(db, run, "verification", "Sol-beoordeling opgeslagen.", review_pending=pending)
    review = validate_review(pending["review"], packet)
    records = [{**review.model_dump(), **pending["usage"], "role": "bulk_verifier"}]
    review, records = _escalate(db, run, packet, review, records, pending, check_running)
    check_running(db, run)
    _contain(db, run, review)
    # Fingerprint the contained state to prevent charging again on an index-only resume.
    fingerprint = hashlib.sha256(
        json.dumps(packet_for_run(db, run), sort_keys=True).encode()
    ).hexdigest()
    checkpoint(
        db,
        run,
        "verification",
        "Onafhankelijke controle vastgelegd; onzekerheden apart gehouden.",
        reviews=records,
        review_input_sha256=fingerprint,
        review_pending={},
    )
