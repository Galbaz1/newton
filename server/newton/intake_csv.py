"""Bounded CSV decoding shared by profiling and explicit preparation."""

import csv
import io

MAX_ROWS = 200_000
MAX_COLUMNS = 100
MAX_FIELD_CHARS = 10_000


def _delimiter(text):
    """Sniff supported delimiters from the first logical record."""
    counts, quoted = dict.fromkeys((",", ";", "\t"), 0), False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "\r\n":
                break
            if char in counts:
                counts[char] += 1
    if not text or quoted:
        raise ValueError("CSV has no valid header")
    return max(counts, key=counts.get)


def _csv_source(data):
    """Return validated headers, delimiter, and a lazily validated row iterator."""
    if not isinstance(data, bytes):
        raise ValueError("CSV input must be bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("CSV contains NUL")
    delimiter = _delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        columns = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise ValueError("CSV has no valid header") from exc
    if not 1 <= len(columns) <= MAX_COLUMNS or any(not name.strip() for name in columns):
        raise ValueError("CSV must have 1..100 nonempty column names")
    if len(set(columns)) != len(columns) or any(len(name) > MAX_FIELD_CHARS for name in columns):
        raise ValueError("CSV has duplicate or oversized column names")
    return columns, delimiter, _rows(reader, len(columns))


def _rows(reader, width):
    """Validate every data record, including those beyond the output sample."""
    try:
        for count, row in enumerate(reader, 1):
            if count > MAX_ROWS:
                raise ValueError("CSV exceeds 200000 data rows")
            if len(row) != width:
                raise ValueError(f"CSV record {count} has an inconsistent column count")
            if any(len(cell) > MAX_FIELD_CHARS for cell in row):
                raise ValueError(f"CSV record {count} exceeds the 10000-character field limit")
            yield row
    except csv.Error as exc:
        raise ValueError("Malformed CSV") from exc
