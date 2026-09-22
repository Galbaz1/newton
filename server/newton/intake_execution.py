"""Validated onboarding actions; generated decisions never rewrite source originals."""

import hashlib
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from . import documents, measurements
from ._schemas import Input, MappingInput
from ._storage import read_original, save_original
from .intake_unit_evidence import UnitSupport, validate_units
from .models import Machine, Page, Source
from .onboarding_models import IntakeItem
from .onboarding_state import checkpoint, known_installations
from .source_scope import bump_source_context


class Installation(Input):
    """A source-supported installation reference, not an inferred physical identity."""

    object_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=2000)
    supporting_item_ids: list[str] = Field(min_length=1, max_length=10)


class Installations(Input):
    installations: list[Installation] = Field(min_length=1, max_length=30)


class Channel(Input):
    column: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=100)
    unit_evidence: str = Field(max_length=1000)
    unit_support: UnitSupport | None = None


class Preparation(Input):
    item_id: str
    object_ref: str | None
    disposition: Literal["usable", "quarantine"]
    reason: str = Field(min_length=1, max_length=2000)
    time_column: str | None = None
    timezone: str | None = None
    channels: list[Channel] = Field(default_factory=list, max_length=30)
    operations: list[dict] = Field(default_factory=list, max_length=10)


class Preparations(Input):
    sources: list[Preparation] = Field(min_length=1, max_length=30)


class PageRequest(Input):
    item_id: str
    pages: list[int] = Field(min_length=1, max_length=5)


def item_for_run(db, run, identifier: str) -> IntakeItem:
    """Resolve an intake ID within its authoritative run, rejecting foreign IDs."""
    item = db.get(IntakeItem, identifier)
    if item is None or item.run_id != run.id:
        raise ValueError("Intake item does not belong to this onboarding run")
    return item


def register(db, run, args: Installations) -> dict:
    """Idempotently create source-supported installations in the run's company."""
    assets = dict(run.state.get("assets", {}))
    known = known_installations(db, run.company_id)
    for entry in args.installations:
        items = [item_for_run(db, run, value) for value in entry.supporting_item_ids]
        pattern = re.compile(rf"(?<![0-9]){re.escape(entry.object_ref)}(?![0-9])", re.I)
        if not any(pattern.search(item.filename + str(item.profile)) for item in items):
            raise ValueError(f"Installation {entry.object_ref} lacks a source reference")
        if entry.object_ref in assets:
            continue
        existing = known.get(entry.object_ref.casefold(), [])
        if len(existing) > 1:
            raise ValueError(f"Prior installation reference {entry.object_ref} is ambiguous")
        if existing:
            identifier, operation = existing[0], "hergebruikt"
        else:
            machine = Machine(
                company_id=run.company_id, name=entry.name, description=entry.description
            )
            db.add(machine)
            db.flush()
            identifier, operation = machine.id, "aangemaakt"
            known[entry.object_ref.casefold()] = [identifier]
        assets[entry.object_ref] = identifier
        checkpoint(db, run, "installation", f"Installatie {operation}: {entry.name}", assets=assets)
    return {"installations": assets}


def read_pages(db, run, args: PageRequest) -> dict:
    """Return at most five explicitly requested extracted pages as untrusted text."""
    item = item_for_run(db, run, args.item_id)
    if item.kind not in {"document", "image"}:
        raise ValueError("Only documents and images contain pages")
    _, _, texts = documents.extract_document(read_original(item), item.media_type)
    if any(number < 1 or number > len(texts) for number in args.pages):
        raise ValueError("Requested page is outside the original document")
    return {
        "item_id": item.id,
        "method": "existing_text_only; use inspect_document for PDF/image interpretation",
        "pages": [{"page": number, "text": texts[number - 1][:12000]} for number in args.pages],
    }


def prepare(db, run, args: Preparations) -> dict:
    """Persist each validated source action independently for safe boundary resumption."""
    results = []
    for entry in args.sources:
        db.refresh(run)
        if run.status != "running":
            return {"paused": True, "results": results}
        item = item_for_run(db, run, entry.item_id)
        if item.kind == "image" and not item.profile.get("visual_observation"):
            raise ValueError(
                "Inspect the image with inspect_document before deciding applicability"
            )
        decision = hashlib.sha256(entry.model_dump_json().encode()).hexdigest()
        previous = db.get(Source, item.source_id) if item.source_id else None
        if (
            previous
            and previous.metadata_json.get("onboarding", {}).get("decision_sha256") == decision
            and previous.metadata_json.get("profile", {}).get("visual_observation")
            == item.profile.get("visual_observation")
        ):
            results.append({"item_id": item.id, "source_id": item.source_id, "status": item.status})
            continue
        validate_units(db, run, entry)
        source, pages = _source(run, item, entry)
        source.metadata_json["onboarding"]["decision_sha256"] = decision
        if previous:
            if previous.sha256 != source.sha256:
                from ._storage import remove_original

                remove_original(source.storage_path)
                raise ValueError(
                    "A different byte transformation requires a separate derived intake"
                )
            from ._storage import remove_original

            remove_original(source.storage_path)
            bump_source_context(db, previous)
            previous.machine_id, previous.status = source.machine_id, source.status
            previous.mapping, previous.metadata_json = source.mapping, source.metadata_json
            previous.version += 1
            source = previous
            pages = []
        else:
            db.add(source)
            db.flush()
        db.add_all(
            Page(source_id=source.id, number=i, text=text) for i, text in enumerate(pages, 1)
        )
        item.source_id, item.machine_id, item.status = source.id, source.machine_id, source.status
        bump_source_context(db, source)
        checkpoint(db, run, "source", f"{item.filename}: {source.status}")
        results.append({"item_id": item.id, "source_id": source.id, "status": source.status})
    return {"results": results}


def _source(run, item, entry: Preparation) -> tuple[Source, list[str]]:
    machine_id = run.state.get("assets", {}).get(entry.object_ref) if entry.object_ref else None
    if entry.object_ref and not machine_id:
        raise ValueError("Register the supported installation before attaching its sources")
    original = read_original(item)
    data, provenance = original, None
    if entry.operations:
        if item.kind != "timeseries":
            raise ValueError("Only CSV sources support preparation operations")
        from .intake_transforms import prepare_csv

        data, provenance = prepare_csv(original, entry.operations)
    metadata = {
        "profile": item.profile,
        "findings": item.findings,
        "onboarding": {
            "run_id": run.id,
            "item_id": item.id,
            "reason": entry.reason,
            "original_sha256": item.sha256,
            "operations": provenance,
        },
    }
    pages, mapping = [], None
    status = "quarantined"
    if item.kind in {"document", "image"}:
        extracted_status, detail, pages = documents.extract_document(data, item.media_type)
        metadata.update(detail)
    if entry.disposition == "usable":
        if item.kind == "timeseries":
            status, detail, mapping = _measurements(data, item, entry)
            metadata.update(detail)
        elif item.kind == "annotation":
            status = "ready"
            metadata["annotations"] = item.profile
        else:
            status = extracted_status
    return Source(
        company_id=run.company_id,
        machine_id=machine_id,
        filename=item.filename,
        media_type=item.media_type,
        kind=item.kind,
        sha256=hashlib.sha256(data).hexdigest(),
        storage_path=save_original(data),
        status=status,
        metadata_json=metadata,
        mapping=mapping,
        data_class=(
            "derived"
            if provenance and data != original and run.data_class == "original"
            else run.data_class
        ),
    ), pages


def _measurements(data: bytes, item, entry: Preparation) -> tuple:
    if not entry.channels or not entry.time_column:
        raise ValueError("Measurements require explicit time and channel mappings")
    profile = item.profile
    if entry.operations:
        from .intake_profile import profile_csv

        profile = profile_csv(data)
    time_profiles = [p for p in profile.get("time_columns", []) if p["column"] == entry.time_column]
    if not time_profiles:
        raise ValueError("Time mapping is not supported by the full-data profile")
    if time_profiles[0].get("backward_count", 0):
        return (
            "quarantined",
            {"error": "Unconfirmed backward time jumps; original order retained"},
            None,
        )
    basis = (
        "source_local"
        if time_profiles[0]["timezone_basis"] == "naive" and not entry.timezone
        else "absolute"
    )
    mappings = []
    for channel in entry.channels:
        if channel.unit != "unknown" and not channel.unit_evidence.strip():
            raise ValueError("A unit needs explicit source evidence, or use unknown")
        mapping = {
            "time_column": entry.time_column,
            "value_column": channel.column,
            "unit": channel.unit,
            "timezone": entry.timezone,
            "time_basis": basis,
        }
        try:
            measurements.validate_mapping(data, MappingInput(**mapping))
        except HTTPException as error:
            raise ValueError(str(error.detail)) from None
        measurements.extract_series(data, item.id, mapping)
        mappings.append(mapping)
    return (
        "ready",
        {
            "channels": [c.model_dump() for c in entry.channels],
            "time_basis": basis,
            "timezone_confirmed": basis == "absolute",
        },
        mappings[0],
    )
