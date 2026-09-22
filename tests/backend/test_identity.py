"""Real auth and owner-scoped company/machine route behavior."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from newton import db
from newton.config import settings
from newton.models import Session, User
from newton.security import COOKIE_NAME, hash_password, token_hash, verify_password
from sqlalchemy import select

PASSWORD = "synthetic password 123"


def test_register_login_rotation_logout_and_hashed_secrets(client):
    """Passwords/tokens stay hashed and revocation invalidates copied cookies."""
    credentials = {"email": "Case@Example.test", "password": PASSWORD}
    response = client.post("/api/auth/register", json=credentials)
    assert response.status_code == 200
    assert set(response.json()) == {"id", "email"}
    assert response.json()["email"] == "case@example.test"
    assert all(
        part in response.headers["set-cookie"].lower()
        for part in ("httponly", "samesite=strict", "expires=", "max-age=")
    )
    old_token = client.cookies.get(COOKIE_NAME)
    with db.SessionLocal() as session:
        user = session.scalar(select(User))
        login = session.scalar(select(Session))
        assert login.id == token_hash(old_token) and login.id != old_token
        assert user.password_hash != PASSWORD and verify_password(PASSWORD, user.password_hash)
        assert login.expires_at.tzinfo is not None
    assert client.post("/api/auth/register", json=credentials).status_code == 409
    assert (
        client.post(
            "/api/auth/login", json={**credentials, "password": "wrong password 123"}
        ).status_code
        == 401
    )
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    new_token = client.cookies.get(COOKIE_NAME)
    assert new_token != old_token
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={old_token}"}).status_code
        == 401
    )
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={new_token}"}).status_code
        == 401
    )
    assert client.post("/api/auth/logout").json() == {"ok": True}


def test_expiration_and_secure_cookie(client, monkeypatch):
    """Expired sessions fail authorization and configured secure cookies are honored."""
    client.post("/api/auth/register", json={"email": "expiry@example.test", "password": PASSWORD})
    with db.SessionLocal() as session:
        login = session.scalar(select(Session))
        login.expires_at = db.utcnow() - timedelta(seconds=1)
        session.commit()
    assert client.get("/api/auth/me").status_code == 401
    monkeypatch.setattr(settings, "cookie_secure", True)
    response = client.post(
        "/api/auth/login",
        json={
            "email": "expiry@example.test",
            "password": PASSWORD,
        },
    )
    assert "secure" in response.headers["set-cookie"].lower()


def test_password_salts():
    """Equivalent passwords receive different salts and malformed hashes fail closed."""
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("other password 123", first)
    assert not verify_password(PASSWORD, "broken")


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid", "password": PASSWORD},
        {"email": "name@example.test", "password": "too short"},
        {"email": "name@example.test", "password": "p" * 201},
        {"email": "a" * 250 + "@example.test", "password": PASSWORD},
    ],
)
def test_invalid_credentials(client, payload):
    """Credential lengths and basic email shape are enforced at the request boundary."""
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_company_machine_shapes_versions_and_owner_scope(client, owner, app):
    """All machine traversals authorize the persisted company and updates advance context."""
    company, machine = owner["company"], owner["machine"]
    assert set(company) == {"id", "name", "description", "created_at"}
    assert company["created_at"].endswith("+00:00")
    assert machine["context_version"] == 1
    assert client.get("/api/companies").json() == [company]
    path = f"/api/companies/{company['id']}/machines"
    assert client.get(path).json() == [machine]
    update = client.patch(f"/api/machines/{machine['id']}", json={"name": "Corrected machine"})
    assert update.json()["context_version"] == 2
    assert update.json()["manufacturer"] == "Fixture"
    assert set(update.json()) == {
        "id",
        "company_id",
        "name",
        "manufacturer",
        "model",
        "description",
        "context_version",
        "created_at",
    }
    assert (
        client.patch(f"/api/machines/{machine['id']}", json={"company_id": "evil"}).status_code
        == 422
    )
    with TestClient(app) as other:
        assert other.get(path).status_code == 401
        other.post("/api/auth/register", json={"email": "other@example.test", "password": PASSWORD})
        assert other.get("/api/companies").json() == []
        assert other.get(path).status_code == 404
        assert other.post(path, json={"name": "Intrusion"}).status_code == 404
        machine_path = f"/api/machines/{machine['id']}"
        assert other.get(machine_path).status_code == 404
        assert other.patch(machine_path, json={"name": "Intrusion"}).status_code == 404
        assert other.get("/api/machines/missing").status_code == 404


@pytest.mark.parametrize(
    "payload", [{}, {"name": None}, {"name": " "}, {"name": "n" * 201}, {"description": "x" * 4001}]
)
def test_invalid_machine_corrections(client, owner, payload):
    """Rejected corrections do not advance the machine context."""
    path = f"/api/machines/{owner['machine']['id']}"
    assert client.patch(path, json=payload).status_code == 422
    assert client.get(path).json()["context_version"] == 1
