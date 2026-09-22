"""Idempotent projection of validated snapshots into native MLflow runs and traces.

Rules: one snapshot is one run; one event is one trace linked to that run; the
supplied timestamps are used verbatim; a repeated snapshot logs nothing new
unless its content hash changed; paused stays RUNNING in MLflow with an explicit
``newton.status`` tag, because MLflow has no paused state.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Keep every write local and synchronous: traces are exported through the global
# tracking URI, so it is pinned per call; usage telemetry is never sent.
for _key in [k for k in os.environ if k.startswith("OTEL_")]:
    # An inherited OTLP exporter config makes MLflow drop spans silently; traces stay in MLflow.
    os.environ.pop(_key, None)
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402
from mlflow import MlflowClient  # noqa: E402
from mlflow.entities import Metric, Param, RunTag

from .snapshots import Snapshot, load_directory
from .state import SyncState

RUN_STATUS = {"running": "RUNNING", "paused": "RUNNING", "finished": "FINISHED", "failed": "FAILED"}
TAG = "newton."


@dataclass
class SyncReport:
    """Outcome of one synchronization pass."""

    created_runs: int = 0
    updated_runs: int = 0
    skipped_runs: int = 0
    created_traces: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)


def _experiment_id(client: MlflowClient, name: str, cache: dict[str, str]) -> str:
    if name not in cache:
        experiment = client.get_experiment_by_name(name)
        cache[name] = experiment.experiment_id if experiment else client.create_experiment(name)
    return cache[name]


USAGE_METRIC_MARKERS = ("token", "usage")


def _is_usage_metric(key: str) -> bool:
    """Whether a metric name reports model usage (``input_tokens``, ``output_tokens_including_reasoning``, ...)."""
    lowered = key.lower()
    return any(marker in lowered for marker in USAGE_METRIC_MARKERS)


def _run_tags(snapshot: Snapshot) -> dict[str, str]:
    tags = {f"{TAG}snapshot_id": snapshot.id, f"{TAG}status": snapshot.status, f"{TAG}schema": "1"}
    tags.update({f"{TAG}source_file": snapshot.source} if snapshot.source else {})
    tags.update(snapshot.tags)
    if not any(_is_usage_metric(key) for key in snapshot.metrics):
        tags[f"{TAG}usage_missing"] = "true"  # missing usage is not zero usage
    return tags


def _log_run(client: MlflowClient, snapshot: Snapshot, entry: dict) -> None:
    run_id = entry["run_id"]
    known_params = set(entry.setdefault("params", []))
    params = [Param(k, v[:6000]) for k, v in snapshot.params.items() if k not in known_params]
    stamp = snapshot.end_ms if snapshot.end_ms is not None else snapshot.start_ms
    metrics = [Metric(k, v, stamp, 0) for k, v in snapshot.metrics.items()]
    tags = [RunTag(k, v[:5000]) for k, v in _run_tags(snapshot).items()]
    client.log_batch(run_id, metrics=metrics, params=params, tags=tags, synchronous=True)
    entry["params"] = sorted(known_params | {p.key for p in params})
    status = RUN_STATUS[snapshot.status]
    if status in {"FINISHED", "FAILED"}:
        client.set_terminated(run_id, status=status, end_time=snapshot.end_ms)
    else:
        client.update_run(run_id, status=status, name=snapshot.name)


def _log_traces(client: MlflowClient, snapshot: Snapshot, entry: dict, experiment_id: str) -> int:
    traces = entry.setdefault("traces", {})
    created = 0
    for event in snapshot.events:
        if event.id in traces:
            continue
        span = client.start_trace(
            name=event.name,
            span_type="CHAIN",
            inputs=event.inputs,
            tags={f"{TAG}event_id": event.id, f"{TAG}snapshot_id": snapshot.id, f"{TAG}event_status": event.status},
            experiment_id=experiment_id,
            start_time_ns=event.start_ms * 1_000_000,
            run_id=entry["run_id"],
        )
        client.end_trace(
            span.trace_id,
            outputs=event.outputs,
            status="OK" if event.status == "ok" else "ERROR",
            end_time_ns=event.end_ms * 1_000_000,
        )
        traces[event.id] = span.trace_id
        created += 1
    return created


def sync_once(tracking_uri: str, snapshot_dir: Path, state_path: Path) -> SyncReport:
    """Project every valid snapshot in ``snapshot_dir`` exactly once per content.

    Args:
        tracking_uri: MLflow tracking URI (loopback HTTP server or sqlite file).
        snapshot_dir: Directory of sanitized ``*.json`` snapshots.
        state_path: Private checkpoint file for id mapping.

    Returns:
        Counts of created/updated/skipped runs, created traces and rejections.
    """
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    state = SyncState(state_path, tracking_uri=tracking_uri)
    snapshots, rejected = load_directory(snapshot_dir)
    report = SyncReport(rejected=rejected)
    experiments: dict[str, str] = {}
    for snapshot in snapshots:
        experiment_id = _experiment_id(client, snapshot.experiment, experiments)
        entry = state.runs.get(snapshot.id)
        if entry is None:
            run = client.create_run(
                experiment_id, start_time=snapshot.start_ms, run_name=snapshot.name, tags=_run_tags(snapshot)
            )
            entry = {"run_id": run.info.run_id, "experiment_id": experiment_id, "hash": None, "params": [], "traces": {}}
            state.runs[snapshot.id] = entry
            state.save()
            report.created_runs += 1
        elif entry["hash"] == snapshot.content_hash:
            # Unchanged content: only repair events whose trace was never checkpointed.
            missing = [event for event in snapshot.events if event.id not in entry["traces"]]
            if not missing:
                report.skipped_runs += 1
                continue
            report.created_traces += _log_traces(client, snapshot, entry, experiment_id)
            state.save()
            report.skipped_runs += 1
            continue
        else:
            report.updated_runs += 1
        _log_run(client, snapshot, entry)
        report.created_traces += _log_traces(client, snapshot, entry, experiment_id)
        entry["hash"] = snapshot.content_hash
        entry["synced_at_ms"] = int(time.time() * 1000)
        state.save()
    return report
