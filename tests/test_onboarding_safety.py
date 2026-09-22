"""Offline onboarding regression tests using synthetic inputs and isolated storage.

Run with ``.venv/bin/python -m pytest tests/test_onboarding_safety.py -vv``.
Remote boundaries fail closed; individual protocol tests substitute explicit local fakes.
Failures represent required safety behavior and are deliberately not marked xfail.
"""

import copy
import hashlib
import json
import socket
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from newton import (
    agent_provider,
    companies,
    db,
    evidence,
    intake_profile,
    onboarding,
    onboarding_agent,
    onboarding_questions,
    onboarding_review_provider,
    onboarding_worker,
    providers,
    retrieval,
    security,
    source_scope,
    sources,
    visual_encoder,
    visual_retrieval,
)
from newton import (
    intake_execution as actions,
)
from newton._storage import read_original, save_original
from newton.config import settings
from newton.models import Company, Machine, Page, Session, Source, User
from newton.onboarding_models import CompanyProfile, IntakeItem, OnboardingRun
from newton.onboarding_state import checkpoint
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

CSV = b"time,value\n2026-09-01 08:00:00,2\n2026-09-01 08:01:00,3\n"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Deny provider, budget, retrieval, encoder and Internet calls in every test."""

    def denied(*args, **kwargs):
        pytest.fail("Unexpected remote or paid boundary reached in offline test")

    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for module, names in (
        (agent_provider, ("interact", "_post")),
        (onboarding_review_provider, ("request",)),
        (providers, ("_post", "answer", "embed")),
        (agent_provider.budget, ("reserve", "settle", "fail")),
        (retrieval, ("connection", "search", "initialize", "remove_source")),
        (visual_retrieval, ("search", "initialize")),
        (visual_encoder, ("_request", "encode_page", "encode_query")),
        (sources, ("remove_index_source",)),
        (onboarding_worker, ("launch", "index_sources")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, denied)
    original_connect = socket.socket.connect

    def connect(connection, address):
        if connection.family in {socket.AF_INET, socket.AF_INET6}:
            denied()
        return original_connect(connection, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Create two independent owners and real SQL sessions in a temporary database."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'onboarding.sqlite'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(onboarding_worker, "SessionLocal", factory)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "private")
    monkeypatch.setattr(settings, "budget_path", tmp_path / "never-created-budget.json")
    monkeypatch.setattr(settings, "visual_encoder_url", "")
    db.init_db()
    application = FastAPI()
    for router in (companies.router, sources.router, onboarding.router):
        application.include_router(router, prefix="/api")
    with factory() as session:
        owners, company_rows, machines, runs = [], [], [], []
        for number in range(2):
            user = User(email=f"synthetic-{number}@example.test", password_hash="unused-fixture")
            session.add(user)
            session.flush()
            company = Company(owner_id=user.id, name=f"Synthetic company {number}")
            session.add(company)
            session.flush()
            machine = Machine(company_id=company.id, name=f"Synthetic machine {number}")
            session.add(machine)
            session.flush()
            run = OnboardingRun(
                company_id=company.id, status="running", state={"assets": {"A1": machine.id}}
            )
            session.add(run)
            session.add(
                Session(
                    id=security.token_hash(f"synthetic-cookie-{number}"),
                    user_id=user.id,
                    expires_at=db.utcnow() + timedelta(hours=1),
                )
            )
            owners.append(user)
            company_rows.append(company)
            machines.append(machine)
            runs.append(run)
        session.commit()
        with TestClient(application) as client:
            client.cookies.set(security.COOKIE_NAME, "synthetic-cookie-0")
            yield SimpleNamespace(
                db=session,
                factory=factory,
                client=client,
                owners=owners,
                companies=company_rows,
                machines=machines,
                runs=runs,
                root=tmp_path,
            )
    engine.dispose()


def _item(world, *, run=None, data=CSV, filename="A1.csv", kind="timeseries"):
    run = run or world.runs[0]
    item = IntakeItem(
        run_id=run.id,
        filename=filename,
        media_type="text/csv" if kind == "timeseries" else "text/plain",
        kind=kind,
        sha256=hashlib.sha256(data).hexdigest(),
        storage_path=save_original(data),
        data_class=run.data_class,
        profile=intake_profile.profile_csv(data) if kind == "timeseries" else {},
        status="profiled",
    )
    world.db.add(item)
    world.db.commit()
    return item


def _entry(item, **changes):
    value = dict(
        item_id=item.id,
        object_ref="A1",
        disposition="usable",
        reason="Synthetic source fixture",
        time_column="time",
        channels=[
            dict(
                column="value",
                label="Recorded value",
                unit="unknown",
                unit_evidence="",
            )
        ],
    )
    value.update(changes)
    return actions.Preparation.model_validate(value)


def _prepare(world, item, *, run=None, **changes):
    result = actions.prepare(
        world.db, run or world.runs[0], actions.Preparations(sources=[_entry(item, **changes)])
    )
    return world.db.get(Source, result["results"][0]["source_id"])


def _source(world, *, company=0, machine="default", status="ready", data_class="original"):
    data = b"Synthetic company manual. No physical equipment."
    source = Source(
        company_id=world.companies[company].id,
        machine_id=world.machines[company].id if machine == "default" else machine,
        filename="synthetic.txt",
        media_type="text/plain",
        kind="document",
        status=status,
        data_class=data_class,
        sha256=hashlib.sha256(data).hexdigest(),
        storage_path=save_original(data),
    )
    world.db.add(source)
    world.db.flush()
    world.db.add(Page(source_id=source.id, number=1, text=data.decode()))
    world.db.commit()
    return source


def _finish(source_ids, **changes):
    question = dict(
        text="What does the supplied source record?",
        origin="source",
        state="ready",
        object_ref="A1",
        source_ids=source_ids,
        reason="Inspect cited synthetic source",
    )
    question.update(changes)
    return onboarding_questions.Finish(
        summary="Synthetic onboarding",
        questions=[question],
        pending_questions=[],
    )


def test_later_batch_reuses_company_installation(world):
    run = OnboardingRun(company_id=world.companies[0].id, status="running", state={})
    world.db.add(run)
    world.db.commit()
    item = _item(world, run=run, filename="a1-second-batch.csv")
    result = actions.register(
        world.db,
        run,
        actions.Installations(
            installations=[
                {
                    "object_ref": "a1",
                    "name": "Same physical installation",
                    "description": "A synthetic derivative, not a second machine",
                    "supporting_item_ids": [item.id],
                }
            ]
        ),
    )
    assert result["installations"]["a1"] == world.machines[0].id
    assert world.db.scalar(select(func.count()).select_from(Machine)) == 2


def test_later_batch_rejects_ambiguous_prior_installation(world):
    other = Machine(company_id=world.companies[0].id, name="Conflicting prior identity")
    world.db.add(other)
    world.db.flush()
    world.db.add(
        OnboardingRun(company_id=world.companies[0].id, state={"assets": {"A1": other.id}})
    )
    run = OnboardingRun(company_id=world.companies[0].id, status="running", state={})
    world.db.add(run)
    world.db.commit()
    item = _item(world, run=run)
    with pytest.raises(ValueError, match="ambiguous"):
        actions.register(
            world.db,
            run,
            actions.Installations(
                installations=[
                    {
                        "object_ref": "A1",
                        "name": "Do not guess",
                        "description": "",
                        "supporting_item_ids": [item.id],
                    }
                ]
            ),
        )


@pytest.mark.parametrize("prior_id", ["foreign", "missing"])
def test_prior_run_cannot_adopt_foreign_or_deleted_machine(world, prior_id):
    identifier = world.machines[1].id if prior_id == "foreign" else "missing-machine"
    world.runs[0].state = {"assets": {"A1": identifier}}
    run = OnboardingRun(company_id=world.companies[0].id, status="running", state={})
    world.db.add(run)
    world.db.commit()
    item = _item(world, run=run)
    result = actions.register(
        world.db,
        run,
        actions.Installations(
            installations=[
                {
                    "object_ref": "A1",
                    "name": "New supported identity",
                    "description": "",
                    "supporting_item_ids": [item.id],
                }
            ]
        ),
    )
    assert result["installations"]["A1"] != identifier
    assert world.db.get(Machine, result["installations"]["A1"]).company_id == run.company_id


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/companies/{company}/onboarding", None),
        ("post", "/companies/{company}/onboarding", {}),
        ("get", "/companies/{company}/sources", None),
        ("get", "/onboarding/{run}", None),
        ("post", "/onboarding/{run}/start", None),
        ("post", "/onboarding/{run}/resume", None),
        ("post", "/onboarding/{run}/pause", None),
        ("post", "/onboarding/{run}/answers", {"question_id": "x", "answer": "Synthetic"}),
    ],
)
def test_foreign_company_and_run_routes_deny(world, method, path, body):
    """Foreign identifiers are denied before worker or mutation side effects."""
    url = "/api" + path.format(company=world.companies[1].id, run=world.runs[1].id)
    response = world.client.request(method, url, json=body)
    assert response.status_code == 404, response.text
    world.db.refresh(world.runs[1])
    assert world.runs[1].status == "running"


def test_foreign_upload_denied_before_storing_bytes(world):
    """An upload to another owner's run cannot create an original or intake row."""
    response = world.client.post(
        f"/api/onboarding/{world.runs[1].id}/files",
        files={"file": ("synthetic.csv", CSV, "text/csv")},
    )
    assert response.status_code == 404
    assert world.db.scalar(select(func.count()).select_from(IntakeItem)) == 0
    assert not list(world.root.rglob("*.bin"))


@pytest.mark.parametrize("suffix", ["original", "pages", "pages/1/image", "series", "annotations"])
def test_foreign_source_routes_deny(world, suffix):
    """Source downloads and views enforce ownership regardless of source kind."""
    source = _source(world, company=1)
    response = world.client.get(f"/api/sources/{source.id}/{suffix}")
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("method,body", [("patch", {"revision": "foreign edit"}), ("delete", None)])
def test_foreign_source_mutations_deny(world, method, body):
    """Foreign source corrections/deletions are rejected before index access."""
    source = _source(world, company=1)
    response = world.client.request(method, f"/api/sources/{source.id}", json=body)
    assert response.status_code == 404
    world.db.refresh(source)
    assert source.revision == ""
    assert read_original(source).startswith(b"Synthetic")


@pytest.mark.parametrize("action", ["prepare", "register", "read_pages"])
@pytest.mark.parametrize("scope", ["foreign_company", "same_company_other_run", "unknown"])
def test_tool_item_references_are_run_scoped(world, action, scope):
    """Tools reject unknown and wrong-run IDs even when a company owner is shared."""
    other_run = world.runs[1]
    if scope == "same_company_other_run":
        other_run = OnboardingRun(company_id=world.companies[0].id)
        world.db.add(other_run)
        world.db.commit()
    item = _item(world, run=other_run)
    identifier = "nonexistent-item" if scope == "unknown" else item.id
    with pytest.raises(ValueError, match="does not belong"):
        if action == "prepare":
            actions.prepare(
                world.db,
                world.runs[0],
                actions.Preparations(sources=[_entry(item, item_id=identifier)]),
            )
        elif action == "register":
            actions.register(
                world.db,
                world.runs[0],
                actions.Installations(
                    installations=[
                        dict(
                            object_ref="A1",
                            name="Synthetic A1",
                            description="Fixture",
                            supporting_item_ids=[identifier],
                        )
                    ]
                ),
            )
        else:
            actions.read_pages(
                world.db, world.runs[0], actions.PageRequest(item_id=identifier, pages=[1])
            )
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0


def test_upload_deduplication_is_run_local_and_original_is_immutable(world):
    """Repeated bytes deduplicate per run while metadata corrections preserve bytes."""
    run = world.runs[0]
    run.status = "draft"
    world.db.commit()
    url = f"/api/onboarding/{run.id}/files"
    first = world.client.post(url, files={"file": ("A1.csv", CSV, "text/csv")})
    second = world.client.post(url, files={"file": ("renamed.csv", CSV, "text/csv")})
    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == second.json()["items"]
    assert len(second.json()["items"]) == 1
    assert len(list(world.root.rglob("*.bin"))) == 1
    item = world.db.get(IntakeItem, first.json()["items"][0]["id"])
    assert read_original(item) == CSV
    assert (settings.data_dir / "originals" / item.storage_path).stat().st_mode & 0o777 == 0o400
    item.profile = intake_profile.profile_csv(CSV)
    run.status = "running"
    world.db.commit()
    source = _prepare(world, item)
    before = (source.sha256, source.storage_path)
    corrected = world.client.patch(
        f"/api/sources/{source.id}", json={"revision": "owner correction"}
    )
    assert corrected.status_code == 200
    world.db.refresh(source)
    assert (source.sha256, source.storage_path) == before
    assert read_original(source) == read_original(item) == CSV
    other = world.client.post(f"/api/companies/{world.companies[0].id}/onboarding", json={}).json()
    repeated = world.client.post(
        f"/api/onboarding/{other['id']}/files", files={"file": ("A1.csv", CSV, "text/csv")}
    )
    assert repeated.status_code == 200
    assert repeated.json()["items"][0]["id"] != item.id


def test_company_library_scope_excludes_foreign_other_machine_and_synthetic(world):
    """SQL evidence and local retrieval inputs admit only applicable real sources."""
    own = _source(world)
    library = _source(world, machine=None)
    derived = _source(world, machine=None, data_class="derived")
    _source(world, company=1, machine=None)
    _source(world, machine=None, data_class="synthetic")
    _source(world, machine=None, data_class="demo")
    another = Machine(company_id=world.companies[0].id, name="Other installation")
    world.db.add(another)
    world.db.commit()
    _source(world, machine=another.id)
    expected = {own.id, library.id, derived.id}
    assert {
        s.id for s in world.db.scalars(source_scope.source_selection(world.machines[0]))
    } == expected
    assert {s["id"] for s in evidence.source_snapshot(world.db, world.machines[0])} == expected
    chunks = retrieval._chunks(world.db, world.companies[0].id, world.machines[0].id)
    assert {chunk["properties"]["source_id"] for chunk in chunks} == expected


def test_naive_times_preserve_source_clock_through_original_series_route(world):
    """Onboarding exposes naive measurements without silently assigning UTC or shifting hours."""
    item = _item(world)
    source = _prepare(world, item)
    response = world.client.get(f"/api/sources/{source.id}/series")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["time_basis"] == "source_local"
    assert result["points"] == [
        {"time": "2026-09-01T08:00:00", "value": 2.0},
        {"time": "2026-09-01T08:01:00", "value": 3.0},
    ]
    assert source.metadata_json["timezone_confirmed"] is False
    assert read_original(item) == CSV


@pytest.mark.parametrize(
    "change,match",
    [
        ({"time_column": "invented"}, "Time mapping"),
        (
            {"channels": [dict(column="absent", label="Absent", unit="unknown", unit_evidence="")]},
            "columns must exist",
        ),
        (
            {"channels": [dict(column="value", label="Value", unit="C", unit_evidence=" ")]},
            "source evidence",
        ),
        ({"operations": [dict(name="fill_gaps", args={})]}, "Unsupported transformation"),
        (
            {"operations": [dict(name="shift_dates", args={"hours": 2})]},
            "Unsupported transformation",
        ),
        ({"object_ref": "UNKNOWN"}, "Register the supported installation"),
    ],
)
def test_unsupported_preparations_do_not_materialize_or_mutate(world, change, match):
    """Invalid mappings, unsupported repairs and unsupported units cannot yield ready sources."""
    item = _item(world)
    with pytest.raises(ValueError, match=match):
        _prepare(world, item, **change)
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0
    assert item.source_id is None
    assert read_original(item) == CSV
    assert len(list(world.root.rglob("*.bin"))) == 1


def test_backward_source_chronology_stays_quarantined(world):
    """Backward clock observations survive unchanged and cannot become a ready series."""
    data = b"time,value\n2026-09-01 08:01:00,3\n2026-09-01 08:00:00,2\n"
    item = _item(world, data=data)
    source = _prepare(world, item)
    assert source.status == "quarantined"
    assert read_original(source) == read_original(item) == data
    assert world.client.get(f"/api/sources/{source.id}/series").status_code == 409


def test_allowed_time_column_rename_remains_usable_with_provenance(world):
    """A supported header rename must map the derived column back to original time evidence."""
    item = _item(world)
    operations = [dict(name="rename_columns", args={"mapping": {"time": "recorded_at"}})]
    source = _prepare(world, item, time_column="recorded_at", operations=operations)
    assert source.status == "ready"
    assert source.mapping["time_column"] == "recorded_at"
    assert source.metadata_json["onboarding"]["operations"]["input_sha256"] == item.sha256
    assert read_original(item) == CSV


@pytest.mark.parametrize("data_class", ["synthetic", "demo"])
def test_transform_cannot_promote_synthetic_input_into_ordinary_evidence(world, data_class):
    """Representation changes must not launder synthetic/demo data into real derived evidence."""
    run = world.runs[0]
    run.data_class = data_class
    world.db.commit()
    data = CSV.replace(b",", b";")
    item = _item(world, data=data)
    source = _prepare(
        world, item, operations=[dict(name="normalize_delimiter", args={"delimiter": ","})]
    )
    assert read_original(item) == data
    assert source.metadata_json["onboarding"]["original_sha256"] == item.sha256
    selected = {s.id for s in world.db.scalars(source_scope.source_selection(world.machines[0]))}
    assert source.id not in selected, (
        f"{data_class} input became ordinary {source.data_class} evidence"
    )


@pytest.mark.parametrize(
    "status,data_class,object_ref",
    [
        ("quarantined", "original", "A1"),
        ("error", "original", "A1"),
        ("ready", "synthetic", "A1"),
        ("ready", "demo", "A1"),
        ("ready", "original", "UNKNOWN"),
    ],
)
def test_finish_downgrades_unavailable_evidence(world, status, data_class, object_ref):
    """Finish cannot convert quarantined, synthetic or unassigned evidence to ready questions."""
    source = _source(world, status=status, data_class=data_class)
    result = onboarding_questions.finish(
        world.db, world.runs[0], _finish([source.id], object_ref=object_ref)
    )
    assert result["ready_questions"] == 0
    assert world.runs[0].state["questions"][0]["state"] == "missing"
    world.db.refresh(source)
    assert source.status == status


@pytest.mark.parametrize("identifier", ["foreign", "unknown"])
@pytest.mark.parametrize("pending", [False, True])
def test_finish_rejects_foreign_or_unknown_source_references(world, identifier, pending):
    """Both starter and clarification references must resolve inside the run's company."""
    source = _source(world, company=1)
    source_id = source.id if identifier == "foreign" else "unknown-source"
    args = _finish([] if pending else [source_id])
    if pending:
        args.pending_questions = [
            onboarding_questions.Pending(
                question="Clarify source", reason="Fixture", source_ids=[source_id]
            )
        ]
    with pytest.raises(ValueError, match="outside this company"):
        onboarding_questions.finish(world.db, world.runs[0], args)
    assert not world.runs[0].state.get("agent_finished")


def test_finish_downgrades_wrong_installation_and_accepts_company_library(world):
    """A shared company manual supports a machine; another machine's manual does not."""
    another = Machine(company_id=world.companies[0].id, name="Other installation")
    world.db.add(another)
    world.db.commit()
    wrong = _source(world, machine=another.id)
    library = _source(world, machine=None)
    result = onboarding_questions.finish(world.db, world.runs[0], _finish([wrong.id]))
    assert result["ready_questions"] == 0
    result = onboarding_questions.finish(world.db, world.runs[0], _finish([library.id]))
    assert result["ready_questions"] == 1


def test_finish_requires_every_uploaded_item_to_be_processed(world):
    """An available manual cannot hide an untouched uploaded measurement file."""
    _item(world)
    source = _source(world)
    with pytest.raises(ValueError, match="Every intake item"):
        onboarding_questions.finish(world.db, world.runs[0], _finish([source.id]))


def test_prepare_replay_after_commit_does_not_duplicate_sources(world):
    """A crash before tool acknowledgement can replay a committed preparation safely."""
    item = _item(world)
    source = _prepare(world, item)
    before = (source.id, source.storage_path, world.machines[0].context_version)
    again = _prepare(world, item)
    world.db.refresh(world.machines[0])
    assert (again.id, again.storage_path, world.machines[0].context_version) == before
    assert world.db.scalar(select(func.count()).select_from(Source)) == 1
    assert len(list(world.root.rglob("*.bin"))) == 2


def test_register_replay_after_commit_does_not_duplicate_installations(world):
    """Replayed installation registration reuses its durable source-backed reference."""
    item = _item(world, filename="B2.csv")
    args = actions.Installations(
        installations=[
            dict(
                object_ref="B2",
                name="Synthetic B2",
                description="Fixture",
                supporting_item_ids=[item.id],
            )
        ]
    )
    first = actions.register(world.db, world.runs[0], args)
    second = actions.register(world.db, world.runs[0], args)
    assert first == second
    assert world.db.scalar(select(func.count()).select_from(Machine)) == 3


def test_finish_replay_preserves_question_and_clarification_identities(world):
    """A finish action replay after commit must retain stable owner-facing identities."""
    source = _source(world)
    args = _finish([source.id])
    args.pending_questions = [
        onboarding_questions.Pending(
            question="Confirm installation identity", reason="Fixture", source_ids=[source.id]
        )
    ]
    onboarding_questions.finish(world.db, world.runs[0], args)
    first = copy.deepcopy(world.runs[0].state)
    onboarding_questions.finish(world.db, world.runs[0], args)
    assert world.runs[0].state["questions"] == first["questions"]
    assert world.runs[0].state["pending_questions"] == first["pending_questions"]


def test_pause_before_tool_keeps_pending_call_and_resume_executes_once(world):
    """A durable pending call survives an owner pause and executes once after resume."""
    run = world.runs[0]
    item = _item(world)
    call = dict(
        type="function_call",
        name="prepare_sources",
        id="synthetic-call",
        arguments={"sources": [_entry(item).model_dump()]},
    )
    checkpoint(
        world.db,
        run,
        "fixture",
        "Synthetic pending call",
        agent_history=[call],
        pending_calls=[call],
    )
    assert world.client.post(f"/api/onboarding/{run.id}/pause").status_code == 200
    with pytest.raises(onboarding_worker.Paused):
        onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert run.state["pending_calls"] == [call]
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0
    run.status = "running"
    world.db.commit()
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert run.state["pending_calls"] == []
    receipts = [s for s in run.state["agent_history"] if s["type"] == "function_result"]
    assert len(receipts) == 1
    assert receipts[0]["call_id"] == "synthetic-call"
    assert world.db.scalar(select(func.count()).select_from(Source)) == 1


def test_pause_between_sources_retains_unfinished_tool_work(world, monkeypatch):
    """Pausing a multi-source action must preserve its unexecuted entries for resume."""
    run = world.runs[0]
    first = _item(world)
    second = _item(world, data=CSV.replace(b",3", b",4"), filename="A1-extra.csv")
    call = dict(
        type="function_call",
        name="prepare_sources",
        id="batch-call",
        arguments={"sources": [_entry(first).model_dump(), _entry(second).model_dump()]},
    )
    checkpoint(
        world.db, run, "fixture", "Synthetic batch", agent_history=[call], pending_calls=[call]
    )
    actual_checkpoint = actions.checkpoint

    def pause_after_first(session, current, kind, message, **changes):
        actual_checkpoint(session, current, kind, message, **changes)
        if kind == "source":
            with world.factory() as owner_session:
                persisted = owner_session.get(OnboardingRun, run.id)
                persisted.status = "paused"
                owner_session.commit()

    monkeypatch.setattr(actions, "checkpoint", pause_after_first)
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert world.db.scalar(select(func.count()).select_from(Source)) == 1
    assert run.state["pending_calls"], (
        "Partial prepare_sources was acknowledged and removed on pause"
    )
    monkeypatch.setattr(actions, "checkpoint", actual_checkpoint)
    run.status = "running"
    world.db.commit()
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert world.db.scalar(select(func.count()).select_from(Source)) == 2


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("execute_shell", {"command": "synthetic non-executed input"}),
        ("prepare_sources", {"sources": [], "company_id": "foreign"}),
    ],
)
def test_unknown_and_invalid_tools_return_errors_without_actions(world, name, arguments):
    """Untrusted model tool names/arguments yield error receipts without side effects."""
    run = world.runs[0]
    call = dict(type="function_call", id="invalid-call", name=name, arguments=arguments)
    checkpoint(world.db, run, "fixture", "Invalid tool", agent_history=[call], pending_calls=[call])
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert "error" in run.state["agent_history"][-1]["result"]
    assert run.state["pending_calls"] == []
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0


def test_invalid_timezone_becomes_tool_error_and_retains_original(world):
    """An unsupported model timezone must be a recoverable tool error, not a loop crash."""
    run = world.runs[0]
    item = _item(world)
    call = dict(
        type="function_call",
        id="timezone-call",
        name="prepare_sources",
        arguments={"sources": [_entry(item, timezone="Mars/Olympus_Mons").model_dump()]},
    )
    checkpoint(
        world.db, run, "fixture", "Invalid timezone", agent_history=[call], pending_calls=[call]
    )
    onboarding_agent.execute_pending(world.db, run, onboarding_worker.check_running)
    assert "error" in run.state["agent_history"][-1]["result"]
    assert read_original(item) == CSV
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0


def test_stateless_agent_preserves_opaque_steps_and_tool_call_ids(world, monkeypatch):
    """The next local fake provider turn receives exact signed steps and matching tool results."""
    run = world.runs[0]
    source = _source(world)
    opaque = {"type": "thought", "signature": "synthetic-opaque-signature", "content": []}
    invalid = dict(
        type="function_call",
        id="opaque-call",
        name="unsupported",
        arguments={},
        thought_signature="synthetic-function-signature",
    )
    finished = dict(
        type="function_call",
        id="finish-call",
        name="finish",
        arguments=_finish([source.id]).model_dump(),
    )
    histories = []

    def interact(run_id, system, history, declarations):
        histories.append(copy.deepcopy(history))
        return {"steps": [opaque, invalid] if len(histories) == 1 else [finished]}

    monkeypatch.setattr(agent_provider, "interact", interact)
    onboarding_agent.run_agent(world.db, run, onboarding_worker.check_running)
    assert len(histories) == 2
    assert histories[1][1:3] == [opaque, invalid]
    assert histories[1][3]["call_id"] == "opaque-call"
    assert "error" in histories[1][3]["result"]
    assert run.state["agent_finished"] is True
    assert run.state["pending_calls"] == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://169.254.169.254/latest",
        "http://10.1.2.3",
        "https://host.local",
        "http://host.internal",
        "http://localhost",
        "http://[::1]",
        "https://user:pass@example.test",
        "file:///etc/passwd",
        "ftp://example.test",
    ],
)
def test_company_url_rejects_nonpublic_locators(url):
    """Company locator validation rejects private hosts, credentials and non-HTTP schemes."""
    with pytest.raises(ValueError):
        onboarding.RunInput(website=url)


def test_profile_claim_provenance_omits_unsupported_urls_and_stays_research(world, monkeypatch):
    """Only tool-returned citations survive; receipt/date/authority persist in company scope."""
    profile = dict(
        overview="Synthetic research summary",
        activities=["Synthetic maintenance"],
        roles=["Mechanic"],
        terminology=["Fixture"],
        identity_uncertain=True,
        limitations=["Synthetic fixture; identity unresolved"],
        claims=[
            dict(
                text="Supported synthetic claim",
                url="https://company.example.test/about",
                title="About",
            ),
            dict(
                text="Unsupported synthetic claim",
                url="https://absent.example.test",
                title="Absent",
            ),
        ],
    )
    receipt = {"attempt_id": "synthetic-no-paid-call", "input_tokens": 1, "output_tokens": 1}
    response = dict(
        steps=[
            dict(type="google_search_result", result={"url": "https://company.example.test/about"}),
            dict(type="model_output", content=[dict(type="text", text=json.dumps(profile))]),
        ],
        _receipt=receipt,
    )
    grounded = dict(
        steps=[
            dict(
                type="model_output",
                content=[
                    dict(
                        type="text",
                        text="Supported synthetic claim",
                        annotations=[
                            dict(
                                type="url_citation",
                                url="https://company.example.test/about",
                                title="About",
                                start_index=0,
                                end_index=len("Supported synthetic claim"),
                            )
                        ],
                    )
                ],
            )
        ],
        _receipt=receipt,
    )
    fake = Mock(side_effect=[grounded, response])
    monkeypatch.setattr(agent_provider, "interact", fake)
    onboarding_worker._research(world.db, world.runs[0])
    onboarding_worker._research(world.db, world.runs[0])
    assert fake.call_count == 2
    row = world.db.get(CompanyProfile, world.companies[0].id)
    assert row.content["authority"] == "public_research_synthesis"
    assert row.content["research_receipt"] == receipt
    assert len(row.content["claims"]) == 1
    assert row.content["claims"][0]["retrieved_at"].endswith("+00:00")
    assert row.content["claims"][0]["url"] == "https://company.example.test/about"
    assert row.content["claims"][0]["text"] == "Supported synthetic claim"
    assert world.db.get(CompanyProfile, world.companies[1].id) is None
    assert world.companies[0].description == ""


def test_offline_worker_journey_profiles_materializes_and_preserves_owner_correction(
    world, monkeypatch
):
    """Exercise the real worker through source intake, fake reasoning, finish and clarification."""
    run = world.runs[0]
    run.status, run.state = "draft", {}
    world.db.commit()
    uploaded = world.client.post(
        f"/api/onboarding/{run.id}/files", files={"file": ("A1.csv", CSV, "text/csv")}
    )
    assert uploaded.status_code == 200
    item_id = uploaded.json()["items"][0]["id"]
    run.status = "running"
    world.db.commit()
    turns = []
    indexed = []

    def interact(run_id, system, history, declarations, schema=None, **kwargs):
        assert run_id == run.id
        turns.append(copy.deepcopy(history))
        if kwargs.get("research") or schema:
            profile = dict(
                overview="No verified organization facts",
                activities=[],
                roles=[],
                terminology=[],
                claims=[],
                identity_uncertain=True,
                limitations=["Offline synthetic research fixture"],
            )
            return dict(
                steps=[
                    dict(type="model_output", content=[dict(type="text", text=json.dumps(profile))])
                ],
                _receipt={"attempt_id": "offline-fixture"},
            )
        if len(turns) == 3:
            inventory = json.loads(history[0]["content"][0]["text"])
            assert inventory["items"][0]["profile"]["row_count"] == 2
            assert inventory["items"][0]["sha256"] == hashlib.sha256(CSV).hexdigest()
            name, arguments = (
                "register_installations",
                dict(
                    installations=[
                        dict(
                            object_ref="A1",
                            name="Synthetic installation A1",
                            description="Source filename A1",
                            supporting_item_ids=[item_id],
                        )
                    ]
                ),
            )
        elif len(turns) == 4:
            with world.factory() as check:
                item = check.get(IntakeItem, item_id)
                name, arguments = "prepare_sources", {"sources": [_entry(item).model_dump()]}
        else:
            with world.factory() as check:
                item = check.get(IntakeItem, item_id)
                args = _finish([item.source_id])
                args.questions[0].capability = "measurement_summary"
                args.questions[0].measurement = onboarding_questions.MeasurementScope(
                    source_id=item.source_id, channel="value"
                )
                args.questions.append(
                    onboarding_questions.Starter(
                        text="Is maintenance history available?",
                        origin="role",
                        state="missing",
                        object_ref="A1",
                        source_ids=[],
                        reason="No maintenance log was uploaded",
                    )
                )
                args.pending_questions = [
                    onboarding_questions.Pending(
                        question="Which source timezone was used?",
                        reason="Naive original timestamps",
                        source_ids=[item.source_id],
                    )
                ]
                name, arguments = "finish", args.model_dump()
        return {
            "steps": [
                dict(
                    type="function_call", id=f"offline-{len(turns)}", name=name, arguments=arguments
                )
            ]
        }

    def index(session, current, check_running):
        check_running(session, current)
        indexed.extend(
            s.id
            for s in session.scalars(
                select(Source).where(
                    Source.company_id == current.company_id, Source.status == "ready"
                )
            )
        )

    monkeypatch.setattr(agent_provider, "interact", interact)
    monkeypatch.setattr(onboarding_worker, "index_sources", index)
    monkeypatch.setattr(
        onboarding_review_provider,
        "request",
        Mock(
            return_value=(
                {"summary": "Synthetic independent boundary", "findings": []},
                {"model": "gpt-5.6-sol", "effort": "medium"},
            )
        ),
    )
    onboarding_worker._work(run.id)
    result = world.client.get(f"/api/onboarding/{run.id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "completed_with_warnings", payload
    assert len(turns) == 5
    assert payload["items"][0]["status"] == "ready"
    assert indexed == [payload["items"][0]["source_id"]]
    assert [q["state"] for q in payload["questions"]] == ["ready", "missing"]
    assert payload["profile"]["authority"] == "public_research_synthesis"
    answer = world.client.post(
        f"/api/onboarding/{run.id}/answers",
        json={
            "question_id": payload["pending_questions"][0]["id"],
            "answer": "Synthetic owner assertion: clock basis is not yet verified",
        },
    )
    assert answer.status_code == 200
    assert answer.json()["pending_questions"][0]["answer"].startswith("Synthetic owner assertion")
    world.db.expire_all()
    item = world.db.get(IntakeItem, item_id)
    source = world.db.get(Source, item.source_id)
    assert read_original(item) == read_original(source) == CSV
    assert source.mapping["time_basis"] == "source_local"
    assert not (world.root / "never-created-budget.json").exists()


@pytest.mark.parametrize("bad_value", ["not-a-number", "NaN", "Infinity"])
def test_invalid_measurement_after_preview_cannot_be_silently_dropped(world, bad_value):
    """All source rows are validated, including invalid observations beyond the preview."""
    rows = [f"2026-09-01 08:{minute:02}:00,{minute}" for minute in range(7)]
    rows.append(f"2026-09-01 08:07:00,{bad_value}")
    data = ("time,value\n" + "\n".join(rows) + "\n").encode()
    item = _item(world, data=data)
    assert len(item.profile["sample_rows"]) == 5
    assert item.profile["row_count"] == 8
    with pytest.raises(ValueError, match="finite number"):
        _prepare(world, item)
    assert item.source_id is None
    assert read_original(item) == data


def test_owner_clarification_during_active_tool_is_denied(world):
    """A running agent cannot have its pending action history erased by clarification."""
    run = world.runs[0]
    checkpoint(
        world.db,
        run,
        "fixture",
        "Pending synthetic clarification",
        pending_questions=[dict(id="q1", question="Clock basis?", reason="Fixture", source_ids=[])],
        pending_calls=[dict(id="pending-tool", name="prepare_sources", arguments={})],
    )
    response = world.client.post(
        f"/api/onboarding/{run.id}/answers",
        json={"question_id": "q1", "answer": "Synthetic owner response"},
    )
    assert response.status_code == 409
    world.db.refresh(run)
    assert run.state["pending_calls"][0]["id"] == "pending-tool"
    assert "answer" not in run.state["pending_questions"][0]


def test_inferred_unit_requires_exact_object_specific_source_support(world):
    """A plausible unit and model-written explanation cannot establish the mapping."""
    item = _item(world)
    with pytest.raises(ValueError, match="source evidence"):
        _prepare(
            world,
            item,
            channels=[
                dict(
                    column="value",
                    label="Temperature",
                    unit="°C",
                    unit_evidence="Normal refrigeration uses Celsius",
                )
            ],
        )
    assert world.db.scalar(select(func.count()).select_from(Source)) == 0


@pytest.mark.parametrize(
    "filename,quote",
    [
        ("general-manual.txt", "Temperature is recorded in °C."),
        ("infoA1.txt", "Invented temperature measurement in °C."),
        ("infoA1.txt", "Temperature"),
    ],
)
def test_general_or_invented_unit_citations_are_rejected(world, filename, quote):
    item = _item(world)
    support = _item(
        world, kind="document", filename=filename, data="Temperature is recorded in °C.".encode()
    )
    with pytest.raises(ValueError, match="General documents|exact page"):
        _prepare(
            world,
            item,
            channels=[
                dict(
                    column="value",
                    label="Temperature",
                    unit="°C",
                    unit_evidence="Source-stated unit",
                    unit_support=dict(item_id=support.id, page=1, quote=quote),
                )
            ],
        )


def test_exact_unit_support_is_preserved_and_foreign_run_is_rejected(world):
    item = _item(world)
    support = _item(
        world,
        kind="document",
        filename="infoA1.txt",
        data="Temperature is recorded in °C.".encode(),
    )
    channel = dict(
        column="value",
        label="Temperature",
        unit="°C",
        unit_evidence="Source-stated unit",
        unit_support=dict(item_id=support.id, page=1, quote="Temperature is recorded in °C."),
    )
    source = _prepare(world, item, channels=[channel])
    assert source.mapping["unit"] == "°C"
    assert source.metadata_json["channels"][0]["unit_support"] == channel["unit_support"]
    foreign = _item(
        world,
        run=world.runs[1],
        kind="document",
        filename="infoA1.txt",
        data="Temperature is recorded in °C.".encode(),
    )
    channel["unit_support"]["item_id"] = foreign.id
    with pytest.raises(ValueError, match="from this run"):
        _prepare(world, item, channels=[channel])


def test_starter_calculation_rewrites_unsupported_prose_and_checks_channel(world):
    item = _item(world)
    source = _prepare(world, item)
    question = _finish(
        [source.id],
        text="Predict the exact failure time",
        capability="measurement_summary",
        measurement=dict(
            source_id=source.id,
            channel="value",
            start="2026-09-01T08:00:00",
            end="2026-09-01T08:01:00",
        ),
    )
    result = onboarding_questions.finish(world.db, world.runs[0], question)
    assert result["ready_questions"] == 1
    stored = world.runs[0].state["questions"][0]
    assert "Predict" not in stored["text"] and "gemiddelde" in stored["text"]
    assert stored["measurement"]["channel"] == "value"
    question.questions[0].measurement.channel = "absent"
    with pytest.raises(ValueError, match="not been established"):
        onboarding_questions.finish(world.db, world.runs[0], question)


def test_csv_cannot_masquerade_as_ready_document_question(world):
    source = _prepare(world, _item(world))
    result = onboarding_questions.finish(
        world.db, world.runs[0], _finish([source.id], capability="document_lookup")
    )
    assert result["ready_questions"] == 0


def test_intake_id_error_identifies_only_its_own_materialized_source(world):
    item = _item(world)
    source = _prepare(world, item)
    with pytest.raises(ValueError) as caught:
        onboarding_questions.finish(world.db, world.runs[0], _finish([item.id]))
    assert source.id in str(caught.value)
    foreign = _item(world, run=world.runs[1])
    with pytest.raises(ValueError) as caught:
        onboarding_questions.finish(world.db, world.runs[0], _finish([foreign.id]))
    assert "outside this company" in str(caught.value)
    assert foreign.id not in str(caught.value)


def test_three_identical_tool_errors_stop_further_paid_turns(world, monkeypatch):
    run = world.runs[0]
    calls = []

    def interact(*args):
        calls.append(True)
        return {
            "steps": [
                {
                    "type": "function_call",
                    "id": f"bad-{len(calls)}",
                    "name": "nonexistent",
                    "arguments": {},
                }
            ]
        }

    monkeypatch.setattr(agent_provider, "interact", interact)
    with pytest.raises(ValueError, match="three times"):
        onboarding_agent.run_agent(world.db, run, onboarding_worker.check_running)
    assert len(calls) == 3
    assert run.state["last_tool_error"]["count"] == 3
    assert run.state["pending_calls"] == []


def test_context_compaction_preserves_full_history_and_rebuilds_authoritative_state(world):
    source = _prepare(world, _item(world))
    run = world.runs[0]
    history = [
        {"type": "user_input", "content": [{"type": "text", "text": "x" * 190000}]},
        {"type": "thought", "signature": "retained-private-signature"},
    ]
    checkpoint(
        world.db,
        run,
        "fixture",
        "Large controlled history",
        agent_history=history,
        pending_calls=[],
        agent_turns=7,
        last_tool_error={"error": "specific correction"},
    )
    onboarding_agent.compact_history(world.db, run)
    archive = settings.data_dir / "onboarding" / run.id / "history-through-turn-7.json"
    assert json.loads(archive.read_text()) == history
    context = json.loads(run.state["agent_history"][0]["content"][0]["text"])
    assert context["materialized_sources"][0]["source_id"] == source.id
    assert context["last_tool_error"]["error"] == "specific correction"
    assert run.state["agent_turns"] == 7
    assert len(run.state["agent_history"]) == 1
