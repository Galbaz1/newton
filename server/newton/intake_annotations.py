"""Bounded Label Studio annotation parsing without inferred label semantics."""

import json
import math
import re
from urllib.parse import unquote, urlsplit

from .intake_profile import _Findings

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 200_000
MAX_TASKS = 10_000
MAX_INTERVALS = 50_000
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_OBJECT = re.compile(r"(?<![a-z0-9])obj[0-9]+(?![a-z0-9])", re.IGNORECASE)


def _pairs(pairs):
    """Reject duplicate JSON keys instead of silently overwriting evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    """Reject JSON extensions for nonfinite numbers."""
    raise ValueError("Nonfinite JSON number")


def _load(data):
    """Load strict UTF-8 JSON and enforce byte, depth, and node bounds."""
    if not isinstance(data, bytes) or len(data) > MAX_JSON_BYTES:
        raise ValueError("Annotations must be bytes, at most 8 MiB")
    try:
        document = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Annotations must be strict UTF-8 JSON") from exc
    stack, nodes = [(document, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("Annotation JSON exceeds depth or node limits")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite JSON number")
        elif isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Annotation JSON contains an unpaired surrogate")
    if not isinstance(document, list) or len(document) > MAX_TASKS:
        raise ValueError("Annotations must be a list of at most 10000 tasks")
    return document


def _identifier(value, kind, findings):
    """Accept bounded identifiers without leaking path-like source strings."""
    if type(value) is int and len(str(value)) <= 128:
        return value
    if isinstance(value, str) and _ID.fullmatch(value):
        return value
    findings.add("unmatched_id", f"Missing or unsupported {kind} ID")
    return None


def _object_ref(task, findings):
    """Extract objNNN only from the source basename, never return source paths."""
    data = task.get("data")
    source = data.get("csv") if isinstance(data, dict) else None
    if isinstance(source, str):
        try:
            basename = unquote(urlsplit(source).path).replace("\\", "/").rsplit("/", 1)[-1]
            match = _OBJECT.search(basename)
            if match and len(match[0]) <= 128:
                return match[0].lower()
        except ValueError:
            pass
    findings.add("unmatched_object_id", "CSV source is missing or its basename has no objNNN ID")
    return None


def _endpoint(value):
    """Accept only bounded scalar source endpoints, without date guessing."""
    if value is None or type(value) in (int, float):
        return value
    if isinstance(value, str) and len(value) <= 256 and "\x00" not in value:
        return value
    raise ValueError("Unsupported interval endpoint")


def _result_intervals(result, identifiers, findings):
    """Preserve known timeseries labels and non-temporal choices verbatim."""
    if not isinstance(result, dict):
        findings.add("unsupported_result", "Result is not an object")
        return []
    kind, value = result.get("type"), result.get("value")
    if kind not in ("timeserieslabels", "choices"):
        findings.add("unsupported_result_type", "Result type is not timeserieslabels or choices")
        return []
    if not isinstance(value, dict):
        findings.add("missing_annotation_value", "Result has no value object")
        return []
    key = "timeserieslabels" if kind == "timeserieslabels" else "choices"
    labels = value.get(key)
    if not isinstance(labels, list) or not labels:
        findings.add("missing_labels", "Result contains no label list; no label inferred")
        return []
    if len(labels) > 100 or any(
        not isinstance(label, str) or not label.strip() or len(label) > 1000 or "\x00" in label
        for label in labels
    ):
        raise ValueError("Labels must be 1..100 nonempty strings of at most 1000 characters")
    if kind == "choices":
        start = end = instant = None
        findings.add(
            "non_temporal_choice", "Choice labels have no inferred temporal extent", "info"
        )
    else:
        start, end = _endpoint(value.get("start")), _endpoint(value.get("end"))
        instant = value.get("instant")
        if instant is not None and type(instant) is not bool:
            raise ValueError("instant must be boolean or null")
        if start is None or (end is None and instant is not True):
            findings.add("missing_interval_bounds", "Source interval has missing bounds; retained")
        if type(start) in (int, float) and type(end) in (int, float) and start > end:
            findings.add("reversed_interval", "Source interval starts after it ends; retained")
        if instant and end is not None and start != end:
            findings.add(
                "contradictory_instant", "Instant has differing start/end bounds; retained"
            )
    return [
        {**identifiers, "label": label, "start": start, "end": end, "instant": instant}
        for label in labels
    ]


def _annotations(task, task_id, object_ref, intervals, findings):
    """Collect all annotations without resolving contradictions between annotators."""
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or not annotations:
        findings.add("missing_annotations", "Task has no annotations; no normal state inferred")
        return
    seen = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            findings.add("unsupported_annotation", "Annotation is not an object")
            continue
        annotation_id = _identifier(annotation.get("id"), "annotation", findings)
        if annotation_id is not None and annotation_id in seen:
            findings.add("duplicate_annotation_id", "Repeated annotation ID; all results retained")
        seen.add(annotation_id)
        identifiers = {"task_id": task_id, "annotation_id": annotation_id, "object_ref": object_ref}
        results = annotation.get("result")
        if not isinstance(results, list) or not results:
            findings.add("missing_results", "Annotation has no results; no normal state inferred")
            continue
        if annotation.get("was_cancelled") is True:
            findings.add(
                "cancelled_annotation", "Cancelled annotation has source results; retained"
            )
        for result in results:
            entries = _result_intervals(result, identifiers, findings)
            if len(intervals) + len(entries) > MAX_INTERVALS:
                raise ValueError("Annotations exceed 50000 intervals")
            intervals.extend(entries)


def parse_annotations(data: bytes) -> dict:
    """Parse Label Studio task lists with explicit source-unspecified semantics.

    Args:
        data: Strict UTF-8 JSON bytes containing tasks with data.csv and annotations.

    Returns:
        Preserved source intervals/choices, safe object references, and bounded
        findings. Missing annotations never imply a normal operating state.

    Raises:
        ValueError: JSON, resource bounds, labels, or interval scalars are invalid.
    """
    tasks, intervals, findings, seen = _load(data), [], _Findings(), set()
    for task in tasks:
        if not isinstance(task, dict):
            findings.add("unsupported_task", "Task is not an object")
            continue
        task_id = _identifier(task.get("id"), "task", findings)
        if task_id is not None and task_id in seen:
            findings.add("duplicate_task_id", "Repeated task ID; all annotations retained")
        seen.add(task_id)
        _annotations(task, task_id, _object_ref(task, findings), intervals, findings)
    return {"intervals": intervals, "interval_semantics": "source_unspecified", **findings.result()}
