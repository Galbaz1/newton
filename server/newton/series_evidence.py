"""Exact channel/period calculations for an authorized investigation context."""

import json
from urllib.parse import urlencode

from pydantic import Field
from sqlalchemy import select

from ._schemas import Input
from ._storage import read_original
from .measurements import extract_series
from .models import Source


class MeasurementScope(Input):
    """Explicit source/channel/period chosen in the question interface."""

    source_id: str = Field(min_length=1, max_length=36)
    channel: str = Field(min_length=1, max_length=200)
    start: str | None = Field(default=None, max_length=100)
    end: str | None = Field(default=None, max_length=100)


def series_evidence(
    db, machine_id: str, first_id: int, scope: MeasurementScope | None = None
) -> list:
    """Calculate every selected original row; never infer a time interval from prose."""
    sources = list(
        db.scalars(
            select(Source)
            .where(
                Source.machine_id == machine_id,
                Source.kind == "timeseries",
                Source.status == "ready",
                Source.data_class.in_(["original", "derived"]),
            )
            .order_by(Source.created_at)
        )
    )
    if scope:
        sources = [s for s in sources if s.id == scope.source_id]
        if not sources:
            raise ValueError("Selected measurements are not available in this machine context")
    evidence = []
    for source in sources[:4]:
        channels = source.metadata_json.get("channels", []) or [
            {"column": source.mapping["value_column"], "unit": source.mapping["unit"]}
        ]
        if scope:
            channels = [c for c in channels if c["column"] == scope.channel]
            if not channels:
                raise ValueError("Selected channel has not been established for this source")
        original = read_original(source)
        for channel in channels[:10]:
            mapping = {**source.mapping, "value_column": channel["column"], "unit": channel["unit"]}
            data = extract_series(
                original,
                source.id,
                mapping,
                scope.start if scope else None,
                scope.end if scope else None,
            )
            evidence.append(_record(source, data, mapping, first_id + len(evidence), scope))
    return evidence


def _record(source, data, mapping: dict, identifier: int, scope) -> dict:
    period = (
        {key: getattr(scope, key) for key in ("start", "end") if getattr(scope, key)}
        if scope
        else {}
    )
    query = (
        urlencode({"channel": mapping["value_column"], **period})
        if source.metadata_json.get("channels")
        else ""
    )
    summary = {
        "unit": data["unit"],
        "time_column": data["time_column"],
        "value_column": data["value_column"],
        "time_basis": data["time_basis"],
        "selected_period": data["selected_period"],
        "summary": data["summary"],
        "first_observations": data["points"][:3],
        "last_visible_observations": data["points"][-3:],
        "visible_series_truncated": data["truncated"],
        "calculation": (
            "Deterministic summary of all valid original CSV rows in the selected period."
        ),
        "findings": source.metadata_json.get("findings", []),
    }
    return {
        "id": f"E{identifier}",
        "source_id": source.id,
        "filename": source.filename,
        "excerpt": json.dumps(summary),
        "revision": source.revision,
        "source_version": source.version,
        "kind": "timeseries",
        "original_sha256": source.sha256,
        "derivation": {
            "method": "csv-all-rows-summary-v1",
            "mapping": mapping,
            "period": period,
            "row_count": data["summary"]["count"],
            "visible_row_count": len(data["points"]),
        },
        "original_url": f"/api/sources/{source.id}/original",
        "series_url": f"/api/sources/{source.id}/series" + (f"?{query}" if query else ""),
    }
