"""Explicit CSV mappings and bounded original observations, without unit inference.

A bad row invalidates the entire series; no observations are dropped. Naive times
remain source-local unless a timezone is established. Ambiguous/nonexistent absolute
times require an explicit offset.
"""

import csv
import io
import math
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from ._schemas import MappingInput

MAX_ROWS = 200_000
MAX_COLUMNS = 100
MAX_FIELD = 10_000
MAX_POINTS = 5000
_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:[Zz]|[+-]\d{2}:\d{2})?"
)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _rows(data: bytes):
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV must use UTF-8 encoding") from None
    if "\x00" in decoded:
        raise ValueError("CSV cannot contain binary NUL bytes")
    from .intake_csv import _delimiter

    reader = csv.reader(
        io.StringIO(decoded, newline=""), delimiter=_delimiter(decoded), strict=True
    )
    try:
        header = next(reader, [])
        if not header or len(header) > MAX_COLUMNS:
            raise ValueError("CSV requires 1 to 100 named columns")
        if any(not column.strip() or len(column) > 200 for column in header):
            raise ValueError("CSV column names must contain 1 to 200 characters")
        if len(set(header)) != len(header):
            raise ValueError("CSV column names must be unique")
        yield header
        for count, row in enumerate(reader, 1):
            if count > MAX_ROWS:
                raise ValueError("CSV exceeds the 200000 observation limit")
            if len(row) != len(header):
                raise ValueError(f"CSV row {count + 1} has missing or extra fields")
            if any(len(value) > MAX_FIELD for value in row):
                raise ValueError(f"CSV row {count + 1} exceeds the 10000 character field limit")
            yield row
    except csv.Error:
        raise ValueError("CSV has malformed quoting or an oversized field") from None


def inspect_csv(data: bytes) -> tuple[str, dict]:
    """Validate CSV shape and return a bounded preview without guessing units/columns."""
    metadata = {}
    try:
        rows = _rows(data)
        header = next(rows)
        metadata = {"columns": header, "sample_rows": [], "row_count": 0}
        if len(header) > 20:
            metadata["warnings"] = ["Preview shows only the first 20 columns"]
        for row in rows:
            metadata["row_count"] += 1
            if len(metadata["sample_rows"]) < 5:
                metadata["sample_rows"].append(dict(zip(header[:20], row[:20], strict=True)))
        if not metadata["row_count"]:
            raise ValueError("CSV must contain at least one observation")
        return "needs_mapping", metadata
    except ValueError as error:
        return "error", {**metadata, "error": str(error)}


def validate_mapping(data: bytes, mapping: MappingInput) -> None:
    """Reject unknown columns/timezones or reuse of one column with public 422 errors."""
    if mapping.timezone:
        try:
            ZoneInfo(mapping.timezone)
        except ValueError, ZoneInfoNotFoundError:
            raise HTTPException(422, "Timezone must be an IANA timezone") from None
    try:
        header = next(_rows(data))
        if mapping.time_column not in header or mapping.value_column not in header:
            raise ValueError("Selected time and value columns must exist in the CSV")
        if mapping.time_column == mapping.value_column:
            raise ValueError("Choose different time and value columns")
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _timestamp(value: str, timezone: str | None, time_basis: str = "absolute") -> datetime:
    value = value.strip()
    if not _TIME.fullmatch(value):
        raise ValueError("time must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.upper())
    except ValueError:
        raise ValueError("time must be a valid ISO timestamp") from None
    if time_basis == "source_local":
        if parsed.tzinfo is not None or timezone:
            raise ValueError("source-local clock times cannot carry an offset or timezone")
        return parsed
    if parsed.tzinfo is not None:
        return parsed
    if not timezone:
        raise ValueError("naive timestamps require an IANA timezone")
    zone = ZoneInfo(timezone)
    candidates = {}
    for fold in (0, 1):
        aware = parsed.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == parsed:
            candidates[utc] = aware
    if len(candidates) != 1:
        raise ValueError("ambiguous or nonexistent local time; supply an explicit UTC offset")
    return next(iter(candidates.values()))


def _observation(row, time_index, value_index, timezone, time_basis):
    timestamp = _timestamp(row[time_index], timezone, time_basis)
    raw_value = row[value_index].strip()
    if not _NUMBER.fullmatch(raw_value):
        raise ValueError("value must be a finite number")
    value = float(raw_value)
    if not math.isfinite(value):
        raise ValueError("value must be a finite number")
    return timestamp, value


def extract_series(
    data: bytes,
    source_id: str,
    mapping: dict,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Validate every observation, preserve row order and summarize beyond the 5000-point cap.

    Args:
        data: Immutable UTF-8 comma-separated original bytes.
        source_id: Authorized source identifier used in the response.
        mapping: Validated explicit time/value columns, unit and optional timezone.
        start: Inclusive ISO start in the selected time basis, or no lower bound.
        end: Inclusive ISO end in the selected time basis, or no upper bound.

    Returns:
        Series JSON with explicit offsets or a declared source-local time basis;
        values are not rescaled.

    Raises:
        ValueError: Any invalid observation, including a bad row beyond the response cap.
    """
    rows = _rows(data)
    header = next(rows)
    time_index, value_index = (
        header.index(mapping["time_column"]),
        header.index(mapping["value_column"]),
    )
    basis = mapping.get("time_basis", "absolute")
    lower = _timestamp(start, mapping.get("timezone"), basis) if start else None
    upper = _timestamp(end, mapping.get("timezone"), basis) if end else None
    if lower and upper and lower > upper:
        raise ValueError("Period start must precede period end")
    points, values, first, last = [], [], None, None
    for number, row in enumerate(rows, 2):
        try:
            time, value = _observation(row, time_index, value_index, mapping.get("timezone"), basis)
            instant = time if basis == "source_local" else time.astimezone(UTC)
        except ValueError as error:
            raise ValueError(f"CSV row {number}: {error}") from None
        except OverflowError:
            raise ValueError(
                f"CSV row {number}: timestamp is outside the supported range"
            ) from None
        if (lower and time < lower) or (upper and time > upper):
            continue
        values.append(value)
        if len(points) < MAX_POINTS:
            points.append({"time": time.isoformat(), "value": value})
        if first is None or instant < first[0]:
            first = (instant, time.isoformat())
        if last is None or instant > last[0]:
            last = (instant, time.isoformat())
    if not values:
        raise ValueError("No observations exist in the selected period")
    count = len(values)
    return {
        "source_id": source_id,
        "time_basis": basis,
        "selected_period": {"start": start, "end": end},
        "unit": mapping["unit"],
        "time_column": mapping["time_column"],
        "value_column": mapping["value_column"],
        "points": points,
        "summary": {
            "count": count,
            "min": min(values),
            "max": max(values),
            "mean": math.fsum(value / count for value in values),
            "start": first[1],
            "end": last[1],
        },
        "truncated": count > MAX_POINTS,
    }
