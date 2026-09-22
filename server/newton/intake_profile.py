"""Deterministic CSV profiling without repairs or timezone assumptions."""

import math
import re
from collections import Counter
from datetime import datetime

from .intake_csv import _csv_source

MAX_FINDINGS = 100
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[Tt ].*)?$")


class _Findings:
    """Count every finding while retaining only a bounded prefix."""

    def __init__(self):
        self.items = []
        self.total = 0

    def add(self, code, message, severity="warning"):
        """Record a finding with bounded descriptive text."""
        self.total += 1
        if len(self.items) < MAX_FINDINGS:
            self.items.append({"code": code, "severity": severity, "message": message[:500]})

    def result(self):
        """Return retained findings and the full finding count."""
        return {
            "findings": self.items,
            "finding_count": self.total,
            "findings_truncated": self.total > len(self.items),
        }


def _column():
    """Create streaming numeric and temporal counters for a column."""
    return {
        "missing_count": 0,
        "finite_count": 0,
        "invalid_count": 0,
        "min": None,
        "max": None,
        "mean": None,
        "binary": True,
        "numeric": False,
        "extreme": 0,
        "time_candidate": False,
        "time_invalid": 0,
        "groups": {},
        "value_counts": Counter(),
        "unlisted_values": 0,
    }


def _category(state, value):
    """Count bounded textual categories without assigning fault semantics."""
    if state["numeric"] or state["groups"]:
        return
    counts = state["value_counts"]
    if len(value) <= 500 and (value in counts or len(counts) < 100):
        counts[value] += 1
    else:
        state["unlisted_values"] += 1


def _numeric(state, value):
    """Update numeric counters; nonfinite numbers are explicitly invalid."""
    try:
        number = float(value)
    except ValueError:
        state["invalid_count"] += 1
        return
    state["numeric"] = True
    if not math.isfinite(number):
        state["invalid_count"] += 1
        return
    state["finite_count"] += 1
    count = state["finite_count"]
    old = state["mean"]
    state["mean"] = number if old is None else old * ((count - 1) / count) + number / count
    state["min"] = number if state["min"] is None else min(number, state["min"])
    state["max"] = number if state["max"] is None else max(number, state["max"])
    state["binary"] &= number in (0, 1)
    state["extreme"] += number > 200


def _time(state, value):
    """Accumulate ISO datetimes separately by timezone awareness."""
    plausible = bool(_ISO.fullmatch(value))
    state["time_candidate"] |= plausible
    try:
        stamp = datetime.fromisoformat(value) if plausible else None
    except ValueError:
        stamp = None
    if stamp is None:
        state["time_invalid"] += 1
        return
    basis = "naive" if stamp.tzinfo is None else "offset"
    group = state["groups"].setdefault(
        basis,
        {
            "seen": set(),
            "previous": None,
            "min": stamp,
            "max": stamp,
            "deltas": Counter(),
            "duplicate_count": 0,
            "backward_count": 0,
        },
    )
    group["duplicate_count"] += stamp in group["seen"]
    group["seen"].add(stamp)
    group["min"], group["max"] = min(group["min"], stamp), max(group["max"], stamp)
    if group["previous"] is not None:
        delta = stamp - group["previous"]
        micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
        group["backward_count"] += micros < 0
        if micros > 0:
            group["deltas"][micros] += 1
    group["previous"] = stamp


def _cadence(group):
    """Use the smallest modal positive delta; count complete missing steps."""
    deltas = group["deltas"]
    step = min(deltas, key=lambda delta: (-deltas[delta], delta)) if deltas else None
    gaps = sum(count for delta, count in deltas.items() if delta > step) if step else 0
    missing = (
        sum((delta // step - 1) * count for delta, count in deltas.items() if delta > step)
        if step
        else 0
    )
    return {
        "min": group["min"].isoformat(),
        "max": group["max"].isoformat(),
        "duplicate_count": group["duplicate_count"],
        "backward_count": group["backward_count"],
        "gap_count": gaps,
        "expected_step_seconds": step / 1_000_000 if step else None,
        "missing_intervals": missing,
        "valid_count": len(group["seen"]) + group["duplicate_count"],
    }


def _time_result(column, state, findings):
    """Summarize all temporal evidence without comparing naive and offset values."""
    groups = {basis: _cadence(group) for basis, group in state["groups"].items()}
    basis = next(iter(groups)) if len(groups) == 1 else "mixed"
    result = {
        "column": column,
        "timezone_basis": basis,
        "min": None,
        "max": None,
        "expected_step_seconds": None,
        "valid_count": 0,
        "missing_count": state["missing_count"],
        "invalid_count": state["time_invalid"],
    }
    for key in ("duplicate_count", "backward_count", "gap_count", "missing_intervals"):
        result[key] = sum(group[key] for group in groups.values())
    if len(groups) == 1:
        result.update(next(iter(groups.values())))
    elif groups:
        result["by_basis"] = groups
        result["valid_count"] = sum(group["valid_count"] for group in groups.values())
        findings.add(
            "mixed_timezones", f"{column[:120]}: naive and offset times; cadence is per basis"
        )
    for key, code in (
        ("invalid_count", "invalid_times"),
        ("duplicate_count", "duplicate_times"),
        ("backward_count", "backward_times"),
        ("gap_count", "time_gaps"),
    ):
        if result[key]:
            findings.add(code, f"{column[:120]}: {result[key]} {key}")
    return result


def _summaries(columns, states, count, findings):
    """Emit numeric/time summaries and findings for every column."""
    numeric, times = [], []
    for column, state in zip(columns, states, strict=True):
        if state["missing_count"]:
            findings.add("missing_values", f"{column[:120]}: {state['missing_count']} blank values")
        if state["missing_count"] == count:
            findings.add("empty_column", f"{column[:120]}: no nonblank values", "info")
        if state["numeric"]:
            keys = ("finite_count", "missing_count", "invalid_count", "min", "max", "mean")
            numeric.append(
                {
                    "column": column,
                    **{key: state[key] for key in keys},
                    "binary": bool(
                        state["binary"] and state["finite_count"] and not state["invalid_count"]
                    ),
                }
            )
            if state["invalid_count"]:
                findings.add(
                    "invalid_numeric", f"{column[:120]}: {state['invalid_count']} invalid numbers"
                )
            if state["extreme"]:
                findings.add(
                    "extreme_numeric",
                    f"{column[:120]}: {state['extreme']} values >200; "
                    "suspect, requiring context; values retained",
                )
        if state["groups"]:
            times.append(_time_result(column, state, findings))
        elif state["time_candidate"]:
            findings.add(
                "invalid_times",
                f"{column[:120]}: {state['time_invalid']} invalid times; "
                "no valid time or timezone basis",
            )
    return numeric, times


def profile_csv(data: bytes) -> dict:
    """Profile every CSV row with bounded summaries and no semantic changes.

    Args:
        data: UTF-8 CSV bytes, optionally with a BOM; comma, semicolon, or tab.

    Returns:
        Column statistics, at most five 20-column samples, and counted findings.
        Blank/whitespace cells are missing; other failed parses are invalid.
        Mixed times have separate by_basis summaries and no shared range/cadence.

    Raises:
        ValueError: Encoding, shape, row, column, or field limits are violated.
    """
    columns, delimiter, rows = _csv_source(data)
    states, findings = [_column() for _ in columns], _Findings()
    seen, samples, duplicates, count = set(), [], 0, 0
    for row in rows:
        count += 1
        key = tuple(row)
        duplicates += key in seen
        seen.add(key)
        if len(samples) < 5:
            samples.append(dict(zip(columns[:20], row[:20], strict=True)))
        for state, value in zip(states, row, strict=True):
            value = value.strip()
            if not value:
                state["missing_count"] += 1
                continue
            _numeric(state, value)
            _time(state, value)
            _category(state, value)
    if not count:
        findings.add("empty_data", "CSV contains a header but no data rows", "info")
    if duplicates:
        findings.add("duplicate_rows", f"{duplicates} repeated rows after their first occurrence")
    numeric, times = _summaries(columns, states, count, findings)
    return {
        "columns": columns,
        "delimiter": delimiter,
        "row_count": count,
        "sample_rows": samples,
        "numeric_columns": numeric,
        "time_columns": times,
        "categorical_columns": [
            {
                "column": column,
                "counts": dict(state["value_counts"]),
                "unlisted_count": state["unlisted_values"],
                "missing_count": state["missing_count"],
                "semantics": "source_assertion",
            }
            for column, state in zip(columns, states, strict=True)
            if not state["numeric"] and not state["groups"]
        ],
        "duplicate_rows": duplicates,
        **findings.result(),
    }
