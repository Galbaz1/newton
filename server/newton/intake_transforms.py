"""Explicit CSV representation repairs with reproducible provenance."""

import csv
import hashlib
import io

from .intake_csv import MAX_FIELD_CHARS, _csv_source


def _operations(operations, columns):
    """Validate and copy a bounded operation list, computing the final header."""
    if not isinstance(operations, list) or len(operations) > 100:
        raise ValueError("operations must be a list of at most 100 entries")
    header, recorded, normalize = columns[:], [], False
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"name", "args"}:
            raise ValueError("Each operation must contain exactly name and args")
        name, args = operation["name"], operation["args"]
        if not isinstance(args, dict):
            raise ValueError("Operation args must be an object")
        if name == "normalize_delimiter":
            if args != {"delimiter": ","}:
                raise ValueError("normalize_delimiter requires delimiter ','")
            normalize = True
            recorded.append({"name": name, "args": {"delimiter": ","}})
        elif name == "rename_columns":
            mapping = args.get("mapping")
            if set(args) != {"mapping"} or not isinstance(mapping, dict):
                raise ValueError("rename_columns requires a mapping object")
            if any(not isinstance(old, str) or old not in header for old in mapping):
                raise ValueError("Rename source must be an existing column")
            if any(
                not isinstance(new, str)
                or not new.strip()
                or "\x00" in new
                or len(new) > MAX_FIELD_CHARS
                for new in mapping.values()
            ):
                raise ValueError("Rename targets must be nonempty bounded column names without NUL")
            header = [mapping.get(column, column) for column in header]
            if len(set(header)) != len(header):
                raise ValueError("Renaming would produce duplicate columns")
            recorded.append({"name": name, "args": {"mapping": dict(mapping)}})
        else:
            raise ValueError("Unsupported transformation")
    return header, recorded, normalize


def prepare_csv(data: bytes, operations: list[dict]) -> tuple[bytes, dict]:
    """Apply only requested delimiter/header repairs, preserving every cell.

    Args:
        data: UTF-8 CSV bytes, optionally with a BOM.
        operations: Explicit name/args objects. normalize_delimiter takes
            {"delimiter": ","}; rename_columns takes {"mapping": {old: new}}.

    Returns:
        Derived UTF-8 bytes and hashes, operations, data row count, and changed
        columns as old/new objects. Effective no-ops return the original bytes.

    Raises:
        ValueError: CSV or operation validation fails; no partial result is returned.
    """
    columns, delimiter, rows = _csv_source(data)
    header, recorded, normalize = _operations(operations, columns)
    target = "," if normalize else delimiter
    changed = [
        {"old": old, "new": new} for old, new in zip(columns, header, strict=True) if old != new
    ]
    stream = io.StringIO(newline="") if changed or target != delimiter else None
    if stream is not None:
        writer = csv.writer(stream, delimiter=target, lineterminator="\r\n")
        writer.writerow(header)
    count = 0
    for row in rows:
        count += 1
        if stream is not None:
            writer.writerow(row)
    result = data if stream is None else stream.getvalue().encode("utf-8")
    return result, {
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "operations": recorded,
        "row_count": count,
        "changed_columns": changed,
    }
