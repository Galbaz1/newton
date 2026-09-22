"""Read-only source evidence with distinct, verified preparation stages."""

from sqlalchemy import select

from ._storage import read_original
from .intake_profile import profile_csv
from .intake_transforms import prepare_csv
from .models import Page
from .onboarding_models import IntakeItem, OnboardingRun


def _compact(profile):
    return {
        key: value
        for key, value in profile.items()
        if key not in {"preview", "sample_rows", "page_samples", "tasks", "annotations"}
    }


def _preparation(db, source, decision):
    item = db.get(IntakeItem, decision["item_id"])
    run = db.get(OnboardingRun, item.run_id) if item else None
    if not run or run.company_id != source.company_id or item.source_id != source.id:
        raise ValueError("CSV preparation input is missing or outside this source scope")
    original, output = read_original(item), read_original(source)
    trace = decision["operations"]
    expected, replayed = prepare_csv(original, trace["operations"])
    if expected != output or replayed != trace or decision["original_sha256"] != item.sha256:
        raise ValueError("CSV preparation does not match its retained input, output and trace")
    return {
        "input_profile": _compact(profile_csv(original)),
        "prepared_output_profile": _compact(profile_csv(output)),
        "preparation_checks": {
            "input_sha256": item.sha256,
            "output_sha256": source.sha256,
            "replayed_output_matches": True,
            "row_count": replayed["row_count"],
            "changed_columns": replayed["changed_columns"],
        },
    }


def source_packet(db, source, profile) -> dict:
    """Build compact reviewer evidence without conflating original and prepared data.

    Transformations are replayed from retained intake bytes and compared exactly to
    the prepared source and recorded trace. Both profiles are calculated from those
    bytes. An inconsistent transformation raises ValueError before paid review;
    stored originals, profiles and decisions are never rewritten by this read.

    Args:
        db: SQLAlchemy session for the retained intake and page records.
        source: Authorized source being evaluated by the reviewer.
        profile: Retained intake profile for a source without a transformation.

    Returns:
        Compact source evidence with explicit preparation stages when applicable.

    Raises:
        ValueError: The original, prepared output, trace or intake scope is invalid.
    """
    decision = source.metadata_json.get("onboarding", {})
    stages = {"input_profile": _compact(profile)}
    if decision.get("operations"):
        stages = _preparation(db, source, decision)
    return {
        "id": source.id,
        "filename": source.filename,
        "kind": source.kind,
        "status": source.status,
        "machine_id": source.machine_id,
        "data_class": source.data_class,
        "version": source.version,
        "sha256": source.sha256,
        "mapping": source.mapping,
        "channels": source.metadata_json.get("channels", []),
        "caveats": source.metadata_json.get("evidence_caveats", []),
        **stages,
        "page_samples": [
            {"page": page.number, "text": page.text[:1200]}
            for page in db.scalars(
                select(Page).where(Page.source_id == source.id).order_by(Page.number).limit(2)
            )
        ],
        "decision": decision,
    }
