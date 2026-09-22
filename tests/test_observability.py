"""The MLflow projection must exclude private document and account content."""

import json

from newton.observability import project_onboarding, publish_onboarding
from test_onboarding_safety import _item
from test_onboarding_safety import offline as offline
from test_onboarding_safety import world as world


def test_projection_contains_counts_and_identity_without_private_content(world):
    item = _item(world, filename="private-client-document.csv")
    run = world.runs[0]
    run.state = {
        **run.state,
        "events": [
            {
                "at": "2026-09-22T08:00:00+00:00",
                "kind": "profile",
                "message": "Private customer content and credentials",
            }
        ],
        "questions": [{"state": "ready", "text": "Private customer question"}],
    }
    world.db.commit()
    result = project_onboarding(world.db, run)
    payload = json.dumps(result)
    assert item.filename not in payload
    assert "Private customer" not in payload
    assert world.owners[0].email not in payload
    assert result["metrics"]["source_count"] == 1
    assert result["events"][0]["start_ms"] == result["events"][0]["end_ms"] == 1790064000000
    assert "cost_eur" not in result["metrics"]  # Missing usage is not a zero-cost claim.


def test_private_snapshot_is_atomic_and_finished_only_when_application_finishes(world):
    run = world.runs[0]
    run.status = "paused"
    world.db.commit()
    publish_onboarding(world.db, run)
    target = world.root / "observability" / f"onboarding-{run.id}.json"
    result = json.loads(target.read_text())
    assert result["status"] == "paused" and result["end_ms"] is None
    assert target.stat().st_mode & 0o777 == 0o600
    assert not target.with_suffix(".pending").exists()
