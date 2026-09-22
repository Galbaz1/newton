"""Write clearly synthetic, disposable canary snapshots for smoke checks.

Nothing here is observed Newton behaviour. The experiment name says so.
"""

from __future__ import annotations

import json
from pathlib import Path

EXPERIMENT = "Newton synthetic canary (disposable)"


def canary_snapshots(base_ms: int = 1_790_000_000_000) -> list[dict]:
    """Deterministic synthetic units covering finished, failed and paused states.

    Args:
        base_ms: Fixed epoch milliseconds so repeated writes stay identical.

    Returns:
        Snapshot documents that satisfy schema 1.
    """
    def unit(i: int, status: str, verdict: str, quality: float, cost_eur: float, latency_ms: int, end: bool) -> dict:
        return {
            "schema": 1,
            "id": f"canary-{i}",
            "experiment": EXPERIMENT,
            "name": f"SYNTHETIC canary case {i} ({status})",
            "status": status,
            "start_ms": base_ms + i * 60_000,
            "end_ms": base_ms + i * 60_000 + latency_ms if end else None,
            "params": {"model": ["gpt-6-astra", "gemini-3.8-flash"][i % 2], "effort": ["low", "high"][i % 2], "case": f"synthetic-case-{i}", "synthetic": True},
            "metrics": {"quality": quality, "cost_eur": cost_eur, "latency_ms": latency_ms, "tokens_total": 1000 + i},
            "tags": {"verdict": verdict, "receipt_sha256": f"{'0' * 60}{i:04d}", "data_class": "synthetic"},
            "events": [
                {"id": f"canary-{i}-retrieve", "name": "retrieve_evidence", "start_ms": base_ms + i * 60_000, "end_ms": base_ms + i * 60_000 + 300, "status": "ok", "inputs": {"question": "synthetic"}, "outputs": {"evidence": 3}},
                {"id": f"canary-{i}-answer", "name": "answer", "start_ms": base_ms + i * 60_000 + 300, "end_ms": base_ms + i * 60_000 + latency_ms, "status": "ok" if status != "failed" else "error", "inputs": {"model": "synthetic"}, "outputs": {"verdict": verdict}},
            ],
        }

    return [
        unit(0, "finished", "supported", 0.9, 0.12, 3700, True),
        unit(1, "finished", "abstained", 0.6, 0.05, 1600, True),
        unit(2, "failed", "provider_error", 0.0, 0.0, 900, True),
        unit(3, "paused", "pending", 0.0, 0.0, 500, False),
    ]


def write(directory: Path) -> list[Path]:
    """Write the canary snapshots as ``*.json`` files.

    Args:
        directory: Target directory (created if missing).

    Returns:
        Written paths.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    written = []
    for doc in canary_snapshots():
        path = directory / f"{doc['id']}.json"
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    import sys

    for path in write(Path(sys.argv[1])):
        print(path)
