"""End-to-end LOCAL HTTP access tests against a disposable authenticated service.

Synthetic canary accounts only, in a temp profile with its own DB/artifacts/auth
store; the server is started here and stopped at teardown. Passwords live only
in the temp secrets file and this process; they are never printed.
"""

from __future__ import annotations

import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

# The module-scoped service fixture runs before the function-scoped conftest fixture,
# so isolate the trace exporter here too (an inherited OTEL_* config drops spans).
for _key in [k for k in os.environ if k.startswith("OTEL_")]:
    os.environ.pop(_key)
os.environ.pop("MLFLOW_TRACKING_URI", None)
os.environ.update(
    {
        "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING": "false",
        "MLFLOW_DISABLE_TELEMETRY": "true",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
    }
)

from newton_observability import accounts
from newton_observability.service import (
    ProfileError,
    init_profile,
    load_profile,
    server_argv,
    server_env,
)

MLFLOW_BIN = str(Path(sys.executable).parent / "mlflow")
API = "/api/2.0/mlflow"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Credentials(tuple):
    """Basic-auth pair whose repr never shows the password (pytest prints call args on failure)."""

    def __repr__(self):
        return f"<credentials {self[0]}>"


class Service:
    """Running canary service plus the identities created during the tests."""

    def __init__(self, profile, process):
        self.profile, self.process = profile, process
        secrets_env = server_env(profile)
        self.admin = Credentials(
            (secrets_env["MLFLOW_AUTH_ADMIN_USERNAME"], secrets_env["MLFLOW_AUTH_ADMIN_PASSWORD"])
        )
        self.passwords = {
            "canary-unapproved": secrets.token_urlsafe(16),
            "canary-student": secrets.token_urlsafe(16),
            "canary-teacher": secrets.token_urlsafe(16),
        }
        self.teaching_id = self.private_id = self.run_id = None

    def url(self, path: str) -> str:
        return self.profile.tracking_uri + path

    def get(self, path, auth, **params):
        return requests.get(self.url(path), auth=auth, params=params, timeout=10)

    def post(self, path, auth, payload):
        return requests.post(self.url(path), auth=auth, json=payload, timeout=10)

    def search_traces(self, auth, experiment_id):
        """v3 trace search (the v2 GET endpoint does not return v3 traces)."""
        body = {
            "locations": [
                {"type": "MLFLOW_EXPERIMENT", "mlflow_experiment": {"experiment_id": experiment_id}}
            ],
            "max_results": 10,
        }
        return self.post("/api/3.0/mlflow/traces/search", auth, body)


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    profile = init_profile(
        tmp_path_factory.mktemp("teaching-canary"), "teaching-canary", _free_port()
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "newton_observability.service", str(profile.root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    svc = Service(profile, process)
    for _ in range(120):
        try:
            if requests.get(svc.url("/health"), timeout=1).status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(0.5)
    else:
        process.kill()
        pytest.fail("canary server did not start")
    _seed(svc)
    yield svc
    # The server forks uvicorn workers: stop the whole session so no canary keeps listening.
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=20)
    time.sleep(1)
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", profile.port)) != 0, "canary server still listening"


def _seed(svc: Service) -> None:
    """As admin: one teaching experiment with a run, an artifact and a trace; one private experiment."""
    os.environ["MLFLOW_TRACKING_USERNAME"], os.environ["MLFLOW_TRACKING_PASSWORD"] = svc.admin
    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(svc.profile.tracking_uri)
    client = MlflowClient(svc.profile.tracking_uri)
    svc.teaching_id = client.create_experiment("Teaching canary (synthetic)")
    svc.private_id = client.create_experiment("Private canary (synthetic, never for students)")
    private_run = client.create_run(svc.private_id, run_name="canary-private")
    svc.private_run_id = private_run.info.run_id
    client.log_metric(svc.private_run_id, "quality", 0.9)
    run = client.create_run(svc.teaching_id, run_name="canary-lesson")
    svc.run_id = run.info.run_id
    client.log_param(svc.run_id, "model", "synthetic")
    client.log_metric(svc.run_id, "quality", 0.5)
    client.log_text(svc.run_id, "synthetic teaching artifact", "note.txt")
    client.set_terminated(svc.run_id)
    span = client.start_trace("lesson", experiment_id=svc.teaching_id, inputs={"q": "synthetic"})
    client.end_trace(span.trace_id, outputs={"a": "synthetic"})
    stored = client.search_traces([svc.teaching_id])
    admin_view = svc.search_traces(svc.admin, svc.teaching_id)
    assert len(stored) == 1, (stored, admin_view.status_code, admin_view.text[:300])
    auth = accounts._client(svc.profile)
    auth.create_user("canary-unapproved", svc.passwords["canary-unapproved"])


def test_unauthenticated_and_legacy_default_admin_are_denied(service):
    assert (
        service.get("/ajax-api/2.0/mlflow/experiments/search", None).status_code == 401
    )  # UI data path
    assert (
        service.get(f"{API}/experiments/get", None, experiment_id=service.teaching_id).status_code
        == 401
    )
    assert (
        service.get(
            f"{API}/experiments/get", ("admin", "password1234"), experiment_id=service.teaching_id
        ).status_code
        == 401
    )
    assert service.get(f"{API}/experiments/search", ("admin", "password1234")).status_code == 401


def test_unapproved_account_sees_nothing(service):
    auth = Credentials(("canary-unapproved", service.passwords["canary-unapproved"]))
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.teaching_id).status_code
        == 403
    )
    assert service.get(f"{API}/artifacts/list", auth, run_id=service.run_id).status_code == 403
    listed = (
        service.post(f"{API}/experiments/search", auth, {"max_results": 100})
        .json()
        .get("experiments", [])
    )
    assert listed == []


def test_approved_student_reads_only_the_selected_experiment(service):
    os.environ[accounts.ACCOUNT_PASSWORD_ENV] = service.passwords["canary-student"]
    record = accounts.approve(
        service.profile, "canary-student", "student", [service.teaching_id], actor="owner (test)"
    )
    assert record["decision"] == "granted" and record["created"] is True
    auth = Credentials(("canary-student", service.passwords["canary-student"]))
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.teaching_id).status_code
        == 200
    )
    traces = service.search_traces(auth, service.teaching_id)
    assert traces.status_code == 200 and len(traces.json().get("traces", [])) == 1, traces.text
    files = service.get(f"{API}/artifacts/list", auth, run_id=service.run_id)
    assert files.status_code == 200 and [f["path"] for f in files.json()["files"]] == ["note.txt"]
    run = service.get(f"{API}/runs/get", auth, run_id=service.run_id)
    assert run.status_code == 200
    artifact_uri = run.json()["run"]["info"][
        "artifact_uri"
    ]  # mlflow-artifacts:/<workspace path>/<exp>/<run>/artifacts
    proxied = service.get(
        f"{API}-artifacts/artifacts/{artifact_uri.split(':/', 1)[1]}/note.txt", auth
    )
    assert proxied.status_code == 200 and proxied.text == "synthetic teaching artifact", (
        artifact_uri,
        proxied.status_code,
    )
    # Unrelated ids and every write/admin action are denied.
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.private_id).status_code
        == 403
    )
    assert service.search_traces(auth, service.private_id).status_code == 403
    assert (
        service.post(f"{API}/runs/create", auth, {"experiment_id": service.teaching_id}).status_code
        == 403
    )
    assert service.post(f"{API}/runs/delete", auth, {"run_id": service.run_id}).status_code == 403
    assert (
        service.post(
            f"{API}/experiments/delete", auth, {"experiment_id": service.teaching_id}
        ).status_code
        == 403
    )
    assert (
        service.post(
            f"{API}/users/create", auth, {"username": "canary-x", "password": "x" * 16}
        ).status_code
        == 403
    )
    assert (
        requests.patch(
            service.url(f"{API}/users/update-admin"),
            auth=auth,
            json={"username": "canary-student", "is_admin": True},
            timeout=10,
        ).status_code
        == 403
    )
    assert service.get(f"{API}/users/get", auth, username="canary-unapproved").status_code == 403


def test_student_cannot_create_anything(service):
    """Originally failing proof (workspaces off → 200); native workspaces now deny with 403."""
    auth = Credentials(("canary-student", service.passwords["canary-student"]))
    created = service.post(f"{API}/experiments/create", auth, {"name": "canary-student-created"})
    assert created.status_code == 403, created.text
    assert (
        service.post(
            f"{API}/registered-models/create", auth, {"name": "canary-student-model"}
        ).status_code
        == 403
    )
    prompt = {
        "name": "canary-student-prompt",
        "tags": [{"key": "mlflow.prompt.is_prompt", "value": "true"}],
    }
    assert service.post(f"{API}/registered-models/create", auth, prompt).status_code == 403
    assert (
        service.post(
            f"{API}/logged-models/create", auth, {"experiment_id": service.teaching_id, "name": "m"}
        ).status_code
        == 403
    )
    # Direct existing ids: own teaching run readable, private run and its metrics not.
    assert service.get(f"{API}/runs/get", auth, run_id=service.run_id).status_code == 200
    assert service.get(f"{API}/runs/get", auth, run_id=service.private_run_id).status_code == 403
    assert (
        service.get(
            f"{API}/metrics/get-history", auth, run_id=service.private_run_id, metric_key="quality"
        ).status_code
        == 403
    )
    assert (
        service.post(
            f"{API}/runs/set-tag", auth, {"run_id": service.run_id, "key": "k", "value": "v"}
        ).status_code
        == 403
    )
    assert service.get(f"{API}/experiments/search", auth, max_results=100).json().get(
        "experiments", []
    ) == [] or [
        e["experiment_id"]
        for e in service.get(f"{API}/experiments/search", auth, max_results=100).json()[
            "experiments"
        ]
    ] == [service.teaching_id]


def test_role_replacement_is_exact(service):
    """Re-approving a student on another experiment drops the earlier grant."""
    auth = Credentials(("canary-student", service.passwords["canary-student"]))
    second = accounts.approve(
        service.profile, "canary-student", "student", [service.private_id], actor="owner (test)"
    )
    assert second["revoked_grants"] == 1
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.teaching_id).status_code
        == 403
    )
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.private_id).status_code
        == 200
    )
    accounts.approve(
        service.profile, "canary-student", "student", [service.teaching_id], actor="owner (test)"
    )


def test_revoked_account_is_denied(service):
    accounts.revoke(service.profile, "canary-student", actor="owner (test)")
    auth = Credentials(("canary-student", service.passwords["canary-student"]))
    assert (
        service.get(f"{API}/experiments/get", auth, experiment_id=service.teaching_id).status_code
        == 401
    )


def test_teaching_admin_manages_this_service_only(service):
    os.environ[accounts.ACCOUNT_PASSWORD_ENV] = service.passwords["canary-teacher"]
    accounts.approve(service.profile, "canary-teacher", "admin", [], actor="owner (test)")
    auth = Credentials(("canary-teacher", service.passwords["canary-teacher"]))
    assert (
        service.post(
            f"{API}/experiments/create", auth, {"name": "Teaching canary 2 (synthetic)"}
        ).status_code
        == 200
    )
    # Demotion to student must drop the creator MANAGE grant on the experiment it created.
    created_id = service.get(
        f"{API}/experiments/get-by-name", auth, experiment_name="Teaching canary 2 (synthetic)"
    ).json()["experiment"]["experiment_id"]
    demoted = accounts.approve(
        service.profile, "canary-teacher", "student", [service.teaching_id], actor="owner (test)"
    )
    assert demoted["revoked_grants"] >= 1
    assert service.get(f"{API}/experiments/get", auth, experiment_id=created_id).status_code == 403
    assert (
        service.post(f"{API}/experiments/delete", auth, {"experiment_id": created_id}).status_code
        == 403
    )
    assert service.get(f"{API}/users/get", auth, username="canary-unapproved").status_code == 403
    accounts.approve(service.profile, "canary-teacher", "admin", [], actor="owner (test)")
    assert (
        service.post(f"{API}/experiments/delete", auth, {"experiment_id": created_id}).status_code
        == 200
    )


def test_assignable_admin_cannot_admit_accounts(service):
    """Owner-only admission: a teaching admin administers experiments but never users."""
    auth = Credentials(("canary-teacher", service.passwords["canary-teacher"]))
    created = service.post(
        f"{API}/experiments/create", auth, {"name": "Teaching canary 3 (synthetic)"}
    )
    assert created.status_code == 200
    exp_id = created.json()["experiment_id"]
    run = service.post(f"{API}/runs/create", auth, {"experiment_id": exp_id})
    assert run.status_code == 200
    assert (
        service.post(
            f"{API}/runs/delete", auth, {"run_id": run.json()["run"]["info"]["run_id"]}
        ).status_code
        == 200
    )
    assert (
        service.post(
            f"{API}/experiments/delete", auth, {"experiment_id": service.teaching_id}
        ).status_code
        == 200
    )
    assert (
        service.post(
            f"{API}/experiments/restore", auth, {"experiment_id": service.teaching_id}
        ).status_code
        == 200
    )
    assert service.search_traces(auth, service.teaching_id).status_code == 200
    assert (
        service.post(
            f"{API}/users/create", auth, {"username": "canary-smuggled", "password": "x" * 16}
        ).status_code
        == 403
    )
    assert (
        requests.patch(
            service.url(f"{API}/users/update-admin"),
            auth=auth,
            json={"username": "canary-teacher", "is_admin": True},
            timeout=10,
        ).status_code
        == 403
    )
    assert service.get(f"{API}/users/get", auth, username="canary-unapproved").status_code == 403
    assert service.get(f"{API}/users/get", auth, username="canary-smuggled").status_code in (
        403,
        404,
    )


def test_credentials_do_not_cross_services(service, tmp_path):
    """A second live profile (own auth DB) rejects every teaching credential, and vice versa."""
    other = init_profile(tmp_path / "private-canary", "private-canary", _free_port())
    assert {other.root, other.artifacts, other.store_uri, other.auth_db_uri}.isdisjoint(
        {
            service.profile.root,
            service.profile.artifacts,
            service.profile.store_uri,
            service.profile.auth_db_uri,
        }
    )
    process = subprocess.Popen(
        server_argv(other, MLFLOW_BIN),
        env=server_env(other),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        for _ in range(120):
            try:
                if requests.get(other.tracking_uri + "/health", timeout=1).status_code == 200:
                    break
            except requests.ConnectionError:
                time.sleep(0.5)
        other_admin = Credentials(
            (
                server_env(other)["MLFLOW_AUTH_ADMIN_USERNAME"],
                server_env(other)["MLFLOW_AUTH_ADMIN_PASSWORD"],
            )
        )
        # Status codes are captured first so a failing assertion never prints credentials.
        statuses = [
            requests.post(
                other.tracking_uri + f"{API}/experiments/search",
                auth=creds,
                json={"max_results": 10},
                timeout=10,
            ).status_code
            for creds in (
                service.admin,
                ("canary-teacher", service.passwords["canary-teacher"]),
                ("canary-unapproved", service.passwords["canary-unapproved"]),
            )
        ]
        assert statuses == [401, 401, 401]
        own = requests.post(
            other.tracking_uri + f"{API}/experiments/search",
            auth=other_admin,
            json={"max_results": 10},
            timeout=10,
        ).status_code
        crossed = service.post(
            f"{API}/experiments/search", other_admin, {"max_results": 10}
        ).status_code
        assert (own, crossed) == (200, 401)
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)


def test_audit_log_records_actor_and_decisions_without_secrets(service):
    lines = service.profile.audit_log.read_text().splitlines()
    assert any('"action": "approve"' in line and '"role": "student"' in line for line in lines)
    assert any(
        '"action": "revoke"' in line and '"account": "canary-student"' in line for line in lines
    )
    assert all('"actor": "owner (test)"' in line for line in lines)
    for password in list(service.passwords.values()) + [service.admin[1]]:
        assert password not in service.profile.audit_log.read_text()
    assert (service.profile.audit_log.stat().st_mode & 0o077) == 0


def test_profile_fails_closed_without_secrets(tmp_path):
    profile = init_profile(tmp_path / "p", "closed", 18990)
    profile.secrets_env.unlink()
    with pytest.raises(ProfileError):
        load_profile(profile.root)
    profile.secrets_env.write_text(
        "MLFLOW_AUTH_ADMIN_USERNAME=a\nMLFLOW_AUTH_ADMIN_PASSWORD=short\nMLFLOW_FLASK_SERVER_SECRET_KEY=k\n"
    )
    os.chmod(profile.secrets_env, 0o600)
    with pytest.raises(ProfileError):
        load_profile(profile.root)


def test_mcp_uses_tracking_server_auth(service):
    """MCP smoke over stdio: the same basic-auth credentials gate every tool call."""
    fastmcp = pytest.importorskip("fastmcp")
    import asyncio
    from fastmcp.client.transports import StdioTransport

    async def run(username, password):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
        env.update(
            {
                "MLFLOW_TRACKING_URI": service.profile.tracking_uri,
                "MLFLOW_TRACKING_USERNAME": username,
                "MLFLOW_TRACKING_PASSWORD": password,
                "MLFLOW_MCP_TOOLS": "experiments",
                "MLFLOW_DISABLE_TELEMETRY": "true",
                "MLFLOW_DISABLE_AGENT_HINT": "1",
            }
        )
        transport = StdioTransport(command=MLFLOW_BIN, args=["mcp", "run"], env=env)
        async with fastmcp.Client(transport) as client:
            names = [tool.name for tool in await client.list_tools()]
            result = await client.call_tool("search_experiments", {}, raise_on_error=False)
            return names, result

    names, ok = asyncio.run(run("canary-teacher", service.passwords["canary-teacher"]))
    assert (
        "search_experiments" in names and not ok.is_error and "Teaching canary" in str(ok.content)
    )
    _, denied = asyncio.run(run("canary-unapproved", "wrong-password-xx"))
    assert denied.is_error or "401" in str(denied.content) or "Unauthorized" in str(denied.content)


def test_service_environment_excludes_unrelated_credentials(tmp_path, monkeypatch):
    profile = init_profile(tmp_path / "isolated-env", "canary", 18990)
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "MLFLOW_TRACKING_PASSWORD",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ]:
        monkeypatch.setenv(key, "must-not-inherit")
    env = server_env(profile)
    assert "must-not-inherit" not in env.values()
    assert env["MLFLOW_ENABLE_WORKSPACES"] == "true"
