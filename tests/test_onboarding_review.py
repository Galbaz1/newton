"""Independent review routing, containment, ownership and durable resumption."""

from unittest.mock import Mock

import pytest
from newton import onboarding_review as review
from newton import onboarding_worker
from newton._storage import read_original
from newton.intake_execution import Preparations, prepare
from newton.models import Source
from newton.onboarding_review_provider import alias_packet, restore_references
from test_onboarding_safety import _entry, _item, _source
from test_onboarding_safety import offline as offline
from test_onboarding_safety import world as world


def prepared(world, filename="A1.csv"):
    item = _item(world, filename=filename)
    prepare(world.db, world.runs[0], Preparations(sources=[_entry(item)]))
    return item


@pytest.mark.parametrize("machine", ["default", None])
@pytest.mark.parametrize("section", ["questions", "pending_questions"])
def test_later_batch_review_includes_linked_existing_source_and_literal_page(
    world, machine, section
):
    item = prepared(world)
    existing = _source(world, machine=machine)
    run = world.runs[0]
    run.state = {
        **run.state,
        section: [
            {"id": "q1", "state": "ready", "source_ids": [existing.id]},
        ],
    }
    world.db.commit()
    packet = review.packet_for_run(world.db, run)
    assert {source["id"] for source in packet["sources"]} == {item.source_id, existing.id}
    linked = next(source for source in packet["sources"] if source["id"] == existing.id)
    assert linked["page_samples"] == [
        {"page": 1, "text": "Synthetic company manual. No physical equipment."},
    ]
    aliased, identities = alias_packet(packet)
    reference = aliased[section][0]["source_ids"][0]
    assert reference.startswith("S") and identities[reference] == existing.id


@pytest.mark.parametrize("missing", [False, True])
def test_later_batch_review_rejects_foreign_or_missing_linked_source_before_call(
    world, monkeypatch, missing
):
    prepared(world)
    foreign = _source(world, company=1)
    run = world.runs[0]
    run.state = {
        **run.state,
        "questions": [
            {"id": "q1", "state": "ready", "source_ids": ["missing" if missing else foreign.id]},
        ],
    }
    world.db.commit()
    request = Mock()
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    with pytest.raises(ValueError, match="outside this company"):
        review.verify(world.db, run, lambda *_: None)
    request.assert_not_called()


def test_earlier_source_concern_disables_new_question_without_mutating_prior_batch(
    world, monkeypatch
):
    prepared(world)
    existing = _source(world)
    run = world.runs[0]
    run.state = {
        **run.state,
        "questions": [
            {"id": "q1", "state": "ready", "source_ids": [existing.id]},
        ],
    }
    world.db.commit()
    before = (existing.status, existing.version, dict(existing.metadata_json))
    monkeypatch.setattr(
        review.onboarding_review_provider,
        "request",
        Mock(return_value=(response([finding(existing.id, [existing.id])]), usage())),
    )
    review.verify(world.db, run, lambda *_: None)
    assert (existing.status, existing.version, existing.metadata_json) == before
    assert run.state["questions"][0]["state"] == "missing"


def response(findings=()):
    return {"summary": "Controle uitgevoerd met zichtbare beperkingen.", "findings": list(findings)}


def finding(target, evidence, **changes):
    return {
        "target_id": target,
        "category": "unsupported_claim",
        "severity": "ordinary",
        "reason": "Bronnen ondersteunen deze toekenning niet.",
        "evidence_ids": evidence,
        "conflict": False,
        **changes,
    }


def usage(escalation=False):
    return {
        "model": "gpt-6-astra" if escalation else "gpt-5.6-sol",
        "effort": "xhigh" if escalation else "medium",
        "attempt_id": "synthetic-test",
    }


def test_regular_review_reuses_checkpoint_without_another_paid_call(world, monkeypatch):
    prepared(world)
    request = Mock(return_value=(response(), usage()))
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    review.verify(world.db, world.runs[0], lambda *_: None)
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert request.call_count == 1
    assert world.runs[0].state["reviews"][0]["model"] == "gpt-5.6-sol"


def test_containment_never_rewrites_originals_or_mappings(world, monkeypatch):
    item = prepared(world)
    before = read_original(item)
    request = Mock(return_value=(response([finding(item.source_id, [item.source_id])]), usage()))
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert item.status == "quarantined"
    assert read_original(item) == before
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert request.call_count == 1


@pytest.mark.parametrize("part", ["target", "evidence"])
def test_foreign_identifiers_rejected_before_writes(world, monkeypatch, part):
    item = prepared(world)
    value = finding(
        "foreign" if part == "target" else item.source_id,
        ["foreign"] if part == "evidence" else [item.source_id],
    )
    monkeypatch.setattr(
        review.onboarding_review_provider,
        "request",
        Mock(return_value=(response([value]), usage())),
    )
    with pytest.raises(ValueError, match="outside"):
        review.verify(world.db, world.runs[0], lambda *_: None)
    assert item.status == "ready"


def test_single_source_cannot_claim_multi_source_conflict(world):
    item = prepared(world)
    packet = review.packet_for_run(world.db, world.runs[0])
    value = finding(item.source_id, [item.source_id], severity="critical", conflict=True)
    with pytest.raises(ValueError, match="two distinct"):
        review.validate_review(response([value]), packet)


def test_only_critical_multi_source_conflict_uses_astra(world, monkeypatch):
    first = prepared(world)
    second = _item(world, data=b"time,value\n2026-09-01 08:00:00,5\n", filename="A1-more.csv")
    prepare(world.db, world.runs[0], Preparations(sources=[_entry(second)]))
    concern = finding(
        first.source_id, [first.source_id, second.source_id], severity="critical", conflict=True
    )
    request = Mock(side_effect=[(response([concern]), usage()), (response(), usage(True))])
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert request.call_count == 2
    assert request.call_args_list[1].kwargs == {"escalation": True}
    assert first.status == "ready"
    assert [r["role"] for r in world.runs[0].state["reviews"]] == [
        "bulk_verifier",
        "critical_verifier",
    ]


def test_contained_ambiguity_does_not_escalate():
    packet = {
        "sources": [{"id": "a", "status": "quarantined"}, {"id": "b", "status": "ready"}],
        "questions": [],
    }
    checked = review.validate_review(
        response([finding("a", ["a", "b"], severity="critical", conflict=True)]), packet
    )
    assert review.critical_findings(checked, packet) == []


def test_pause_after_sol_preserves_review_without_repaying(world, monkeypatch):
    prepared(world)
    request = Mock(return_value=(response(), usage()))
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    checks = Mock(side_effect=[None, RuntimeError("paused")])
    with pytest.raises(RuntimeError, match="paused"):
        review.verify(world.db, world.runs[0], checks)
    assert world.runs[0].state["review_pending"]
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert request.call_count == 1


def test_quarantine_disables_dependent_starter(world, monkeypatch):
    item = prepared(world)
    run = world.runs[0]
    run.state = {
        **run.state,
        "questions": [{"id": "q1", "state": "ready", "source_ids": [item.source_id]}],
    }
    world.db.commit()
    monkeypatch.setattr(
        review.onboarding_review_provider,
        "request",
        Mock(return_value=(response([finding(item.source_id, [item.source_id])]), usage())),
    )
    review.verify(world.db, run, lambda *_: None)
    assert run.state["questions"][0]["state"] == "missing"


def test_short_references_round_trip_without_changing_evidence_text():
    packet = {
        "sources": [{"id": "source-uuid", "text": "Keep source-uuid in this quotation."}],
        "questions": [{"id": "question-uuid", "source_ids": ["source-uuid"]}],
    }
    aliased, identities = alias_packet(packet)
    assert aliased["sources"][0]["id"] == "S1"
    assert aliased["sources"][0]["text"] == packet["sources"][0]["text"]
    assert aliased["questions"][0]["source_ids"] == ["S1"]
    result = restore_references(response([finding("Q1", ["S1"])]), identities)
    assert result["findings"][0]["target_id"] == "question-uuid"
    assert result["findings"][0]["evidence_ids"] == ["source-uuid"]
    assert packet["sources"][0]["id"] == "source-uuid"


@pytest.mark.parametrize("target,evidence", [("S2", ["S1"]), ("S1", ["invented"])])
def test_unknown_short_reference_cannot_be_repaired(target, evidence):
    with pytest.raises(ValueError, match="unknown short reference"):
        restore_references(response([finding(target, evidence)]), {"S1": "real-source"})


@pytest.mark.parametrize("channels", [[], ["not-a-column"]])
def test_unit_finding_requires_exact_affected_columns(world, channels):
    item = prepared(world)
    packet = review.packet_for_run(world.db, world.runs[0])
    concern = finding(item.source_id, [item.source_id], category="unit", channels=channels)
    with pytest.raises(ValueError, match="exact channels"):
        review.validate_review(response([concern]), packet)


def test_unit_containment_preserves_other_channels_originals_and_prior_assertion(
    world, monkeypatch
):
    item = prepared(world)
    source = world.db.get(Source, item.source_id)
    channels = [
        {"column": "value", "unit": "°C", "unit_support": {"page": 2}},
        {"column": "door", "unit": "boolean", "unit_support": {"page": 3}},
    ]
    source.metadata_json = {**source.metadata_json, "channels": channels}
    source.mapping = {**source.mapping, "unit": "°C"}
    world.db.commit()
    before, version = read_original(item), source.version
    concern = finding(item.source_id, [item.source_id], category="unit", channels=["value"])
    request = Mock(return_value=(response([concern, concern]), usage()))
    monkeypatch.setattr(review.onboarding_review_provider, "request", request)
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert source.status == item.status == "ready"
    assert source.mapping["unit"] == "unknown"
    checked = source.metadata_json["channels"]
    assert checked[0]["unit"] == "unknown" and checked[0]["unit_support"] is None
    assert checked[0]["prior_unit_assertion"] == channels[0]
    assert checked[1] == channels[1]
    assert source.version == version + 1
    assert read_original(item) == before
    review.verify(world.db, world.runs[0], lambda *_: None)
    assert source.version == version + 1 and request.call_count == 1


def test_question_unit_concern_disables_question_without_changing_source(world, monkeypatch):
    item = prepared(world)
    run = world.runs[0]
    source = world.db.get(Source, item.source_id)
    before, version = read_original(item), source.version
    run.state = {
        **run.state,
        "questions": [{"id": "q1", "state": "ready", "source_ids": [source.id]}],
    }
    world.db.commit()
    concern = finding("q1", [source.id], category="unit", channels=["value"])
    monkeypatch.setattr(
        review.onboarding_review_provider,
        "request",
        Mock(return_value=(response([concern]), usage())),
    )
    review.verify(world.db, run, lambda *_: None)
    assert run.state["questions"][0]["state"] == "missing"
    assert source.status == "ready" and source.version == version
    assert read_original(item) == before


@pytest.mark.parametrize("evidence,channels", [(["s2"], ["value"]), (["s1"], ["invented"])])
def test_question_unit_concern_requires_cited_linked_channel(evidence, channels):
    packet = {
        "sources": [
            {"id": "s1", "channels": [{"column": "value"}]},
            {"id": "s2", "channels": [{"column": "value"}]},
        ],
        "questions": [{"id": "q1", "source_ids": ["s1"]}],
    }
    concern = finding("q1", evidence, category="unit", channels=channels)
    with pytest.raises(ValueError, match="exact channels"):
        review.validate_review(response([concern]), packet)


def test_worker_failure_preserves_onboarding_summary_for_resumption(world, monkeypatch):
    run = world.runs[0]
    run.summary = "Bruikbare meetreeksen; onzekere eenheden blijven onbekend."
    world.db.commit()
    monkeypatch.setattr(
        onboarding_worker, "_research", Mock(side_effect=ValueError("test failure"))
    )
    onboarding_worker._work(run.id)
    world.db.refresh(run)
    assert run.status == "error"
    assert run.summary == "Bruikbare meetreeksen; onzekere eenheden blijven onbekend."
    assert run.state["events"][-1]["message"] == "test failure"
