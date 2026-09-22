"""Atomic JSON checkpoint mapping snapshot and event ids to MLflow identities."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

VERSION = 1


class SyncState:
    """Persisted mapping that makes repeated synchronization idempotent.

    Attributes:
        path: JSON file under the private state directory.
        runs: ``snapshot_id -> {run_id, experiment_id, hash, params, traces}``.
    """

    def __init__(self, path: Path, tracking_uri: str | None = None) -> None:
        self.path = path
        self.tracking_uri = tracking_uri
        self.runs: dict[str, dict] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != VERSION:
                raise ValueError(f"unsupported state version in {path}")
            bound = data.get("tracking_uri")
            if tracking_uri is not None and bound not in (None, tracking_uri):
                # Run ids are only meaningful in the backend that issued them.
                raise ValueError(f"checkpoint {path} belongs to tracking URI {bound!r}, not {tracking_uri!r}")
            self.runs = data.get("runs", {})

    def save(self) -> None:
        """Write the state atomically (temp file + rename) with private mode."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".json")
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            payload = {"version": VERSION, "tracking_uri": self.tracking_uri, "runs": self.runs}
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)
