"""Exercise evidence invalidation, late answers and tenant denial through the API."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from newton import (
    auth,
    companies,
    documents,
    investigation_run,
    investigations,
    providers,
    retrieval,
    sources,
)
from newton.config import settings
from newton.db import Base, get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    sessions = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    app = FastAPI()

    def session():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = session
    for router in [
        auth.router,
        companies.router,
        sources.router,
        investigations.router,
        investigation_run.router,
    ]:
        app.include_router(router, prefix="/api")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "private")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(retrieval, "search", lambda *args: [])
    monkeypatch.setattr(providers, "answer", lambda *args: ("No source evidence yet.", {}))
    with TestClient(app) as browser:
        yield browser
    engine.dispose()


def onboard(client, email="one@example.test"):
    assert client.post(
        "/api/auth/register", json={"email": email, "password": "synthetic-password-123"}
    ).is_success
    company = client.post(
        "/api/companies", json={"name": "Test company", "description": "Fixture"}
    ).json()
    machine = client.post(
        f"/api/companies/{company['id']}/machines",
        json={"name": "Fixture pump", "manufacturer": "", "model": "", "description": "Synthetic"},
    ).json()
    investigation = client.post("/api/investigations", json={"machine_id": machine["id"]}).json()
    return machine, investigation


def ask(client, machine, investigation, text="What evidence is available?"):
    return client.post(
        f"/api/investigations/{investigation['id']}/messages",
        json={
            "text": text,
            "model": "gpt-6-astra",
            "expected_context_version": machine["context_version"],
        },
    )


def test_other_account_cannot_read_or_answer_conversation(client):
    machine, investigation = onboard(client)
    client.post("/api/auth/logout")
    onboard(client, "two@example.test")
    assert client.get(f"/api/investigations/{investigation['id']}").status_code == 404
    assert ask(client, machine, investigation).status_code == 404


def test_answer_retains_original_mapping_after_csv_correction(client):
    """Historical evidence retains the exact bytes and timezone interpretation it used."""
    machine, investigation = onboard(client)
    original = b"time,value\n2026-09-21T09:00:00,7\n2026-09-21T10:00:00,9\n"
    source = client.post(
        f"/api/machines/{machine['id']}/sources",
        files={"file": ("synthetic.csv", original, "text/csv")},
    ).json()
    mapping = {"time_column": "time", "value_column": "value", "unit": "bar", "timezone": "UTC"}
    path = f"/api/sources/{source['id']}"
    client.patch(path, json={"mapping": mapping}).raise_for_status()
    machine = client.get(f"/api/machines/{machine['id']}").json()
    response = ask(client, machine, investigation)
    assert response.status_code == 200, response.text
    before = response.json()["evidence"][0]
    assert before["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert before["derivation"]["mapping"] == {**mapping, "time_basis": "absolute"}
    assert before["derivation"]["method"] == "csv-all-rows-summary-v1"
    assert before["derivation"]["row_count"] == 2
    client.patch(
        path, json={"mapping": {**mapping, "unit": "kPa", "timezone": "Europe/Amsterdam"}}
    ).raise_for_status()
    history = client.get(f"/api/investigations/{investigation['id']}").json()["messages"]
    assert history[-1]["status"] == "superseded"
    assert history[-1]["evidence"][0] == before
    assert client.get(path + "/original").content == original


def test_source_correction_supersedes_answer_and_rejects_old_context(client):
    machine, investigation = onboard(client)
    response = ask(client, machine, investigation)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "complete"
    uploaded = client.post(
        f"/api/machines/{machine['id']}/sources",
        files={"file": ("manual.txt", b"Original fixture.", "text/plain")},
    )
    assert uploaded.is_success, uploaded.text
    history = client.get(f"/api/investigations/{investigation['id']}").json()
    assert history["messages"][-1]["status"] == "superseded"
    assert ask(client, machine, investigation).status_code == 409


def test_scope_correction_during_inference_fences_late_answer(client, monkeypatch):
    machine, investigation = onboard(client)
    started, release = threading.Event(), threading.Event()

    def delayed(*args):
        started.set()
        assert release.wait(10)
        return "Answer from the earlier scope.", {}

    monkeypatch.setattr(providers, "answer", delayed)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(ask, client, machine, investigation)
        assert started.wait(5)
        correction = client.post(
            f"/api/investigations/{investigation['id']}/corrections",
            json={
                "text": "The measurement is from a different location.",
                "expected_context_version": machine["context_version"],
            },
        )
        release.set()
        assert correction.status_code == 200, correction.text
        response = future.result(timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "superseded"


def test_revoked_session_during_inference_returns_no_answer(client, monkeypatch):
    machine, investigation = onboard(client)
    started, release = threading.Event(), threading.Event()

    def delayed(*args):
        started.set()
        assert release.wait(10)
        return "Private answer.", {}

    monkeypatch.setattr(providers, "answer", delayed)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(ask, client, machine, investigation)
        assert started.wait(5)
        assert client.post("/api/auth/logout").is_success
        release.set()
        response = future.result(timeout=10)
    assert response.status_code == 401
    assert "Private answer" not in response.text
    assert client.post(
        "/api/auth/login",
        json={"email": "one@example.test", "password": "synthetic-password-123"},
    ).is_success
    history = client.get(f"/api/investigations/{investigation['id']}").json()
    assert history["messages"][-1]["status"] == "error"
    assert "Private answer" not in str(history)
    monkeypatch.setattr(providers, "answer", lambda *args: ("A new authorized answer.", {}))
    assert ask(client, machine, investigation).json()["status"] == "complete"


def test_missing_original_records_error_and_releases_run(client, monkeypatch):
    from fastapi import HTTPException

    machine, investigation = onboard(client)

    def missing(*args):
        raise HTTPException(503, "Original bytes are unavailable.")

    monkeypatch.setattr(investigation_run, "_series_evidence", missing)
    response = ask(client, machine, investigation)
    assert response.json()["status"] == "error"
    assert "Original bytes are unavailable" in response.json()["text"]
    monkeypatch.setattr(investigation_run, "_series_evidence", lambda *args: [])
    assert ask(client, machine, investigation).json()["status"] == "complete"


def test_excluded_pdf_warning_cannot_reuse_its_citation_for_measurements(client, monkeypatch):
    machine, investigation = onboard(client)
    monkeypatch.setattr(retrieval, "search", lambda *args: [{"id": "E1"}, {"id": "E2"}])
    monkeypatch.setattr(investigation_run.visual_retrieval, "search", lambda *args: ([], []))

    def bounded(db, machine, evidence, images):
        evidence.pop()
        return [], [], ["[E2] not supplied due to input limits"]

    def answer(system, prompt, *args):
        assert "[E2] not supplied due to input limits" in prompt
        return "Observed [E1] and calculated [E3].", {}

    monkeypatch.setattr(investigation_run.answer_documents, "attach_pdfs", bounded)
    monkeypatch.setattr(
        investigation_run,
        "_series_evidence",
        lambda db, machine_id, first_id, scope: [{"id": f"E{first_id}"}],
    )
    monkeypatch.setattr(providers, "answer", answer)
    result = ask(client, machine, investigation).json()
    assert result["status"] == "complete"
    assert [record["id"] for record in result["evidence"]] == ["E1", "E3"]
    assert result["warnings"] == ["[E2] not supplied due to input limits"]


def test_explicit_pdf_page_is_attached_before_semantic_retrieval(client, monkeypatch):
    from test_native_pdf import synthetic_pdf

    machine, investigation = onboard(client)
    uploaded = client.post(
        f"/api/machines/{machine['id']}/sources",
        files={"file": ("manual.pdf", synthetic_pdf(), "application/pdf")},
    )
    assert uploaded.is_success, uploaded.text
    machine = client.get(f"/api/machines/{machine['id']}").json()

    def answer(_, prompt, __, images, pdfs):
        assert images == ()
        assert len(pdfs) == 1
        assert documents.extract_document(pdfs[0][1], "application/pdf")[2][1] == "SOURCE THIRD"
        assert '"page": 3' in prompt
        return "Page 3 is available. [E1]", {}

    monkeypatch.setattr(providers, "answer", answer)
    result = ask(client, machine, investigation, "What is on page 3 of manual.pdf?").json()
    assert result["status"] == "complete"
    assert result["evidence"][0]["page"] == 3
    assert result["evidence"][0]["model_input"]["original_pages"] == [2, 3, 4]
