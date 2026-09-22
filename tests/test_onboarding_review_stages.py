"""Review evidence distinguishes immutable intake from verified prepared bytes."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from newton import onboarding_review as review
from newton._storage import read_original, save_original
from newton.intake_execution import Preparations, prepare
from newton.models import Source
from test_onboarding_safety import _entry, _item
from test_onboarding_safety import offline as offline
from test_onboarding_safety import world as world


def normalized(world):
    item = _item(world, data=b"time;value\n2026-09-01 08:00:00;2\n2026-09-01 08:01:00;3\n")
    entry = _entry(item, operations=[{"name": "normalize_delimiter", "args": {"delimiter": ","}}])
    prepare(world.db, world.runs[0], Preparations(sources=[entry]))
    return item, world.db.get(Source, item.source_id)


def test_review_has_actual_profiles_for_both_csv_stages(world):
    item, source = normalized(world)
    before = (read_original(item), read_original(source), deepcopy(source.metadata_json))
    packet = review.packet_for_run(world.db, world.runs[0])["sources"][0]
    assert "profile" not in packet
    assert packet["input_profile"]["delimiter"] == ";"
    assert packet["prepared_output_profile"]["delimiter"] == ","
    assert packet["input_profile"]["row_count"] == 2
    assert packet["prepared_output_profile"]["row_count"] == 2
    assert packet["preparation_checks"] == {
        "input_sha256": item.sha256,
        "output_sha256": source.sha256,
        "replayed_output_matches": True,
        "row_count": 2,
        "changed_columns": [],
    }
    assert (read_original(item), read_original(source), source.metadata_json) == before


@pytest.mark.parametrize(
    "corruption", ["output", "input_hash", "output_hash", "row_count", "foreign_item"]
)
def test_invalid_transformation_is_rejected_before_paid_review(world, monkeypatch, corruption):
    item, source = normalized(world)
    metadata = deepcopy(source.metadata_json)
    trace = metadata["onboarding"]["operations"]
    if corruption == "output":
        import hashlib

        wrong = read_original(source).replace(b",3", b",9")
        source.storage_path, source.sha256 = save_original(wrong), hashlib.sha256(wrong).hexdigest()
        trace["output_sha256"] = source.sha256
    elif corruption == "foreign_item":
        foreign = _item(world, run=world.runs[1])
        metadata["onboarding"]["item_id"] = foreign.id
    else:
        trace[
            {
                "input_hash": "input_sha256",
                "output_hash": "output_sha256",
                "row_count": "row_count",
            }[corruption]
        ] = "wrong"
    source.metadata_json = metadata
    world.db.commit()
    request = Mock()
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    with pytest.raises(ValueError, match="preparation"):
        review.verify(world.db, world.runs[0], lambda *_: None)
    request.assert_not_called()


def test_column_rename_profiles_describe_actual_stages(world):
    item = _item(world)
    entry = _entry(
        item,
        operations=[{"name": "rename_columns", "args": {"mapping": {"value": "temperature"}}}],
        channels=[
            {
                "column": "temperature",
                "label": "Recorded value",
                "unit": "unknown",
                "unit_evidence": "",
            }
        ],
    )
    prepare(world.db, world.runs[0], Preparations(sources=[entry]))
    packet = review.packet_for_run(world.db, world.runs[0])["sources"][0]
    assert packet["input_profile"]["columns"] == ["time", "value"]
    assert packet["prepared_output_profile"]["columns"] == ["time", "temperature"]
    assert packet["preparation_checks"]["changed_columns"] == [
        {"old": "value", "new": "temperature"}
    ]
