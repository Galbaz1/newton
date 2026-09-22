"""Synthetic-snapshot tests: validation, idempotency and native readback."""

import json
from pathlib import Path

import pytest
from mlflow import MlflowClient

from newton_observability import canary
from newton_observability.snapshots import SnapshotError, parse
from newton_observability.sync import sync_once


@pytest.fixture
def store(tmp_path: Path) -> tuple[str, Path, Path]:
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    snapshots = tmp_path / "snapshots"
    canary.write(snapshots)
    return uri, snapshots, tmp_path / "state" / "sync-state.json"


def test_sync_is_idempotent_and_readable(store):
    uri, snapshots, state = store
    first = sync_once(uri, snapshots, state)
    assert (first.created_runs, first.created_traces, first.rejected) == (4, 8, [])
    second = sync_once(uri, snapshots, state)
    assert (second.created_runs, second.updated_runs, second.skipped_runs, second.created_traces) == (0, 0, 4, 0)

    client = MlflowClient(tracking_uri=uri)
    experiment = client.get_experiment_by_name(canary.EXPERIMENT)
    runs = client.search_runs([experiment.experiment_id], "tags.`newton.snapshot_id` = 'canary-2'")
    assert len(runs) == 1
    failed = runs[0]
    assert failed.info.status == "FAILED" and failed.info.end_time == 1_790_000_000_000 + 120_000 + 900
    assert failed.data.params["model"] == "gpt-6-astra" and failed.data.params["synthetic"] == "true"
    assert failed.data.metrics["cost_eur"] == 0.0 and failed.data.tags["verdict"] == "provider_error"

    finished = client.search_runs([experiment.experiment_id], "attributes.status = 'FINISHED'")
    assert {r.data.tags["newton.snapshot_id"] for r in finished} == {"canary-0", "canary-1"}
    paused = client.search_runs([experiment.experiment_id], "tags.`newton.status` = 'paused'")[0]
    assert paused.info.status == "RUNNING" and paused.info.end_time is None

    traces = client.search_traces([experiment.experiment_id], "tags.`newton.snapshot_id` = 'canary-2'")
    assert len(traces) == 2
    answer = next(t for t in traces if t.info.tags["newton.event_id"] == "canary-2-answer")
    assert answer.info.state == "ERROR" and answer.info.request_time == 1_790_000_000_000 + 120_000 + 300
    span = answer.data.spans[0]
    assert span.start_time_ns == answer.info.request_time * 1_000_000  # supplied start_ms, verbatim
    assert span.end_time_ns is not None and span.end_time_ns > span.start_time_ns
    linked = answer.info.trace_metadata.get("mlflow.sourceRun") or answer.info.request_metadata.get("mlflow.sourceRun")
    assert linked == failed.info.run_id, (answer.info.run_id, answer.info.request_metadata)
    assert json.loads(answer.data.spans[0].outputs if isinstance(answer.data.spans[0].outputs, str) else json.dumps(answer.data.spans[0].outputs)) == {"verdict": "provider_error"}
    assert len(client.search_traces([experiment.experiment_id], max_results=100)) == 8


def test_changed_snapshot_updates_without_duplicate_traces(store):
    uri, snapshots, state = store
    sync_once(uri, snapshots, state)
    path = snapshots / "canary-3.json"
    doc = json.loads(path.read_text())
    doc.update(status="finished", end_ms=doc["start_ms"] + 5000)
    doc["metrics"]["quality"] = 0.7
    path.write_text(json.dumps(doc))
    report = sync_once(uri, snapshots, state)
    assert (report.updated_runs, report.created_traces, report.skipped_runs) == (1, 0, 3)
    client = MlflowClient(tracking_uri=uri)
    experiment = client.get_experiment_by_name(canary.EXPERIMENT)
    run = client.search_runs([experiment.experiment_id], "tags.`newton.snapshot_id` = 'canary-3'")[0]
    assert run.info.status == "FINISHED" and run.data.metrics["quality"] == 0.7
    assert len(client.search_traces([experiment.experiment_id], max_results=100)) == 8


def test_rejects_invalid_values(store):
    uri, snapshots, state = store
    base = json.loads((snapshots / "canary-0.json").read_text())
    for patch, reason in [
        ({"metrics": {"cost": 1.0}}, "currency"),
        ({"metrics": {"quality": True}}, "finite number"),
        ({"status": "finished", "end_ms": None}, "requires end_ms"),
        ({"experiment": "Newton production"}, "experiment"),
        ({"events": [base["events"][0], base["events"][0]]}, "unique"),
    ]:
        with pytest.raises(SnapshotError, match=reason):
            parse({**base, **patch})
    (snapshots / "broken.json").write_text("{not json")
    report = sync_once(uri, snapshots, state)
    assert report.rejected and report.rejected[0][0] == "broken.json" and report.created_runs == 4
