"""Local hostname and cross-origin boundaries reject requests before authentication."""

from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from newton import main
from newton.main import app


def test_rebound_hostname_cannot_register_or_read_api():
    # Do not enter the lifespan: rejecting Host must not require database/index I/O.
    browser = TestClient(app, base_url="http://rebound.example.test")
    response = browser.post(
        "/api/auth/register",
        headers={"Origin": "http://rebound.example.test"},
        json={"email": "intruder@example.test", "password": "synthetic-password-123"},
    )
    assert response.status_code == 400
    assert browser.get("/api/openapi.json").status_code == 400
    browser.close()


def test_declared_oversized_body_rejected_without_parsing():
    with closing(TestClient(app, base_url="http://127.0.0.1:18765")) as browser:
        response = browser.post(
            "/api/auth/register",
            headers={"Content-Length": str(65 * 1024 * 1024 + 1)},
            content=b"not valid JSON",
        )
    assert response.status_code == 413


def test_chunked_oversized_body_rejected_without_content_length():
    def chunks():
        for _ in range(66):
            yield b"x" * (1024 * 1024)

    with closing(TestClient(app, base_url="http://127.0.0.1:18765")) as browser:
        response = browser.post(
            "/api/auth/register", headers={"Content-Type": "application/json"}, content=chunks()
        )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413


@pytest.mark.parametrize("startup_fails", [False, True])
def test_lifespan_disposes_pool_on_shutdown_or_failed_startup(monkeypatch, startup_fails):
    disposed = []
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main.onboarding_worker, "recover", lambda db: None)
    monkeypatch.setattr(main.retrieval, "initialize", lambda: None)
    monkeypatch.setattr(main.engine, "dispose", lambda: disposed.append(True))

    def initialize_visual():
        if startup_fails:
            raise RuntimeError("Synthetic startup failure")

    monkeypatch.setattr(main.visual_retrieval, "initialize", initialize_visual)
    if startup_fails:
        with pytest.raises(RuntimeError, match="Synthetic startup failure"), TestClient(app):
            pass
    else:
        with TestClient(app):
            assert not disposed
    assert disposed == [True]


def test_loopback_schema_and_cross_origin_write_boundary():
    browser = TestClient(app, base_url="http://127.0.0.1:18765")
    assert browser.get("/api/openapi.json").status_code == 200
    assert (
        browser.post(
            "/api/companies",
            headers={"Origin": "https://foreign.example.test"},
            json={"name": "Must not be created"},
        ).status_code
        == 403
    )
    browser.close()
