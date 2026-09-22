"""Validate sanitized evidence snapshots before anything reaches MLflow.

The coordinator writes these JSON projections; this module never scans other
files. Invalid snapshots are rejected with a specific reason and skipped.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1
EXPERIMENTS = frozenset(
    {
        "Newton onboarding",
        "Newton verifier evaluation",
        "Newton recovery evaluation",
        "Newton prompt optimization",
        "Newton synthetic canary (disposable)",
    }
)
STATUSES = frozenset({"running", "finished", "failed", "paused"})
EVENT_STATUSES = frozenset({"ok", "error"})
MAX_EVENT_PAYLOAD = 16_384
SCALARS = (str, int, float, bool)


class SnapshotError(ValueError):
    """A snapshot violates the schema; nothing from it is logged."""


@dataclass(frozen=True)
class Event:
    """One traced action with the original supplied timestamps."""

    id: str
    name: str
    start_ms: int
    end_ms: int
    status: str
    inputs: dict
    outputs: dict


@dataclass(frozen=True)
class Snapshot:
    """One evidence unit mapped to exactly one MLflow run."""

    id: str
    experiment: str
    name: str
    status: str
    start_ms: int
    end_ms: int | None
    params: dict[str, str]
    metrics: dict[str, float]
    tags: dict[str, str]
    events: tuple[Event, ...]
    content_hash: str
    source: str = field(default="")


def _int(value, label: str, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError(f"{label} must be a non-negative integer millisecond timestamp")
    return value


def _metrics(raw) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise SnapshotError("metrics must be an object")
    out: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise SnapshotError("metric keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SnapshotError(f"metric {key!r} must be a finite number")
        if key.startswith("cost") and key not in {"cost_eur", "cost_usd"}:
            raise SnapshotError(f"metric {key!r}: cost metrics must state currency (cost_eur|cost_usd)")
        out[key] = float(value)
    return out


def _strings(raw, label: str, scalars: bool = False) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise SnapshotError(f"{label} must be an object")
    out: dict[str, str] = {}
    for key, value in raw.items():
        ok = isinstance(value, SCALARS) if scalars else isinstance(value, str)
        if not isinstance(key, str) or not key or not ok:
            raise SnapshotError(f"{label} entries must be string keys with {'scalar' if scalars else 'string'} values")
        out[key] = value if isinstance(value, str) else json.dumps(value)
    return out


def _payload(raw, label: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SnapshotError(f"{label} must be an object")
    if len(json.dumps(raw, ensure_ascii=False)) > MAX_EVENT_PAYLOAD:
        raise SnapshotError(f"{label} exceeds {MAX_EVENT_PAYLOAD} characters")
    return raw


def _event(raw, seen: set[str]) -> Event:
    if not isinstance(raw, dict):
        raise SnapshotError("events must be objects")
    identifier, name = raw.get("id"), raw.get("name")
    if not isinstance(identifier, str) or not identifier or identifier in seen:
        raise SnapshotError("event ids must be unique non-empty strings")
    if not isinstance(name, str) or not name:
        raise SnapshotError(f"event {identifier}: name is required")
    if raw.get("status") not in EVENT_STATUSES:
        raise SnapshotError(f"event {identifier}: status must be ok|error")
    start, end = _int(raw.get("start_ms"), f"event {identifier}.start_ms"), _int(raw.get("end_ms"), f"event {identifier}.end_ms")
    if end < start:
        raise SnapshotError(f"event {identifier}: end_ms precedes start_ms")
    seen.add(identifier)
    return Event(identifier, name, start, end, raw["status"], _payload(raw.get("inputs"), "inputs"), _payload(raw.get("outputs"), "outputs"))


def parse(raw: dict, source: str = "") -> Snapshot:
    """Validate one decoded snapshot document.

    Args:
        raw: Decoded JSON object.
        source: Display path used in error messages and MLflow tags.

    Returns:
        The validated snapshot with a canonical content hash.

    Raises:
        SnapshotError: Any schema or value violation.
    """
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise SnapshotError(f"schema must be {SCHEMA}")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise SnapshotError("id must be a non-empty string")
    if raw.get("experiment") not in EXPERIMENTS:
        raise SnapshotError(f"experiment must be one of {sorted(EXPERIMENTS)}")
    if raw.get("status") not in STATUSES:
        raise SnapshotError("status must be running|finished|failed|paused")
    start = _int(raw.get("start_ms"), "start_ms")
    end = _int(raw.get("end_ms"), "end_ms", allow_none=True)
    if raw["status"] in {"finished", "failed"} and end is None:
        raise SnapshotError(f"status {raw['status']} requires end_ms")
    if end is not None and end < start:
        raise SnapshotError("end_ms precedes start_ms")
    seen: set[str] = set()
    events = tuple(_event(item, seen) for item in raw.get("events", []) or [])
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return Snapshot(
        id=identifier,
        experiment=raw["experiment"],
        name=str(raw.get("name") or identifier),
        status=raw["status"],
        start_ms=start,
        end_ms=end,
        params=_strings(raw.get("params", {}), "params", scalars=True),
        metrics=_metrics(raw.get("metrics", {})),
        tags=_strings(raw.get("tags", {}), "tags"),
        events=events,
        content_hash=digest,
        source=source,
    )


def load_directory(directory: Path) -> tuple[list[Snapshot], list[tuple[str, str]]]:
    """Read every top-level ``*.json`` file in ``directory``; never recurse.

    Args:
        directory: Snapshot directory written by the coordinator.

    Returns:
        Valid snapshots and ``(filename, reason)`` pairs for rejected files.
    """
    valid: list[Snapshot] = []
    rejected: list[tuple[str, str]] = []
    if not directory.is_dir():
        return valid, rejected
    for path in sorted(directory.glob("*.json")):
        try:
            valid.append(parse(json.loads(path.read_text(encoding="utf-8")), path.name))
        except (SnapshotError, ValueError, OSError) as error:
            rejected.append((path.name, str(error)))
    return valid, rejected
