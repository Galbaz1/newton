"""Generic private MLflow service profile: fail-closed basic-auth configuration.

One profile is one isolated service (own backend DB, own artifacts, own auth DB,
own secrets) under a runtime directory given as an argument. Nothing here knows
any host name: services only ever bind 127.0.0.1. Private and teaching services
are two profiles in two different runtime directories; they never share a path
and each auth DB rejects the other's credentials (tests/test_access.py). The
server runs with native workspaces enabled (``MLFLOW_ENABLE_WORKSPACES``), so
creating experiments, models, prompts or runs needs a workspace-wide grant that
only admins hold. Limits: both services run under the same OS account, so this
is MLflow-level separation, not filesystem or network sandboxing.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

AUTH_APP = "basic-auth"
MIN_PASSWORD = 12  # mlflow.utils.validation._validate_password in 3.16.1
DEFAULT_PERMISSION = "NO_PERMISSIONS"  # READ would leak every experiment to any account


class ProfileError(RuntimeError):
    """A profile is missing, incomplete or would start unauthenticated."""


@dataclass(frozen=True)
class Profile:
    """Resolved runtime layout of one service profile.

    Attributes:
        root: Runtime directory (mode 0700) holding everything below.
        name: Human label, e.g. ``private`` or ``teaching``; never a host name.
        port: Loopback port the server binds.
        admin_username: Bootstrap admin account name (MLflow RBAC admin, not a machine account).
    """

    root: Path
    name: str
    port: int
    admin_username: str

    @property
    def store_uri(self) -> str:
        return f"sqlite:///{self.root / 'mlflow.db'}"

    @property
    def auth_db_uri(self) -> str:
        return f"sqlite:///{self.root / 'auth.db'}"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def auth_ini(self) -> Path:
        return self.root / "auth.ini"

    @property
    def secrets_env(self) -> Path:
        return self.root / "secrets.env"

    @property
    def audit_log(self) -> Path:
        return self.root / "access-audit.jsonl"

    @property
    def tracking_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _write_private(path: Path, text: str, mode: int) -> None:
    """Atomically write ``text`` to ``path`` with the given mode (never world-readable)."""
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, mode)
    os.replace(temp, path)


def _auth_ini(profile: Profile) -> str:
    return (
        "[mlflow]\n"
        f"default_permission = {DEFAULT_PERMISSION}\n"
        f"database_uri = {profile.auth_db_uri}\n"
        f"admin_username = {profile.admin_username}\n"
        "authorization_function = mlflow.server.auth:authenticate_request_basic_auth\n"
        "grant_default_workspace_access = false\n"
        "auth_cache_ttl_seconds = 0\n"
    )


def init_profile(root: Path, name: str, port: int, admin_username: str = "newton-admin") -> Profile:
    """Create a fail-closed profile: private dirs, auth.ini and generated secrets.

    Args:
        root: Runtime directory; created with mode 0700 if missing.
        name: Profile label; must not contain path separators.
        port: Loopback port (1024-65535).
        admin_username: Bootstrap RBAC admin name.

    Returns:
        The profile. Secrets are generated once and never printed; re-running
        keeps existing secrets so the bootstrapped admin password stays valid.
    """
    if "/" in name or not name:
        raise ProfileError("profile name must be a plain label")
    if not 1024 <= port <= 65535:
        raise ProfileError("port must be between 1024 and 65535")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    profile = Profile(root=root, name=name, port=port, admin_username=admin_username)
    profile.artifacts.mkdir(exist_ok=True, mode=0o700)
    os.chmod(profile.artifacts, 0o700)
    _write_private(profile.auth_ini, _auth_ini(profile), 0o600)
    if not profile.secrets_env.is_file():
        env = (
            f"MLFLOW_AUTH_ADMIN_USERNAME={admin_username}\n"
            f"MLFLOW_AUTH_ADMIN_PASSWORD={secrets.token_urlsafe(24)}\n"
            f"MLFLOW_FLASK_SERVER_SECRET_KEY={secrets.token_urlsafe(32)}\n"
        )
        _write_private(profile.secrets_env, env, 0o600)
    manifest = {"name": name, "port": port, "admin_username": admin_username, "auth_app": AUTH_APP}
    _write_private(root / "profile.json", json.dumps(manifest, indent=2) + "\n", 0o600)
    return profile


def load_profile(root: Path) -> Profile:
    """Read an initialized profile; raises ``ProfileError`` if it cannot start closed."""
    root = root.resolve()
    manifest_path = root / "profile.json"
    if not manifest_path.is_file():
        raise ProfileError(f"{root} is not an initialized profile (run init-profile)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile = Profile(
        root=root,
        name=manifest["name"],
        port=int(manifest["port"]),
        admin_username=manifest["admin_username"],
    )
    check_secrets(profile)
    return profile


def read_secrets(profile: Profile) -> dict[str, str]:
    """Parse ``secrets.env`` (KEY=VALUE lines). Never log the result."""
    if not profile.secrets_env.is_file():
        raise ProfileError(f"missing {profile.secrets_env}; refusing to start without secrets")
    values: dict[str, str] = {}
    for line in profile.secrets_env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def check_secrets(profile: Profile) -> None:
    """Fail closed: both secrets present, private mode, admin password long enough."""
    values = read_secrets(profile)
    mode = profile.secrets_env.stat().st_mode & 0o777
    if mode & 0o077:
        raise ProfileError(f"{profile.secrets_env} must be mode 0600, is {oct(mode)}")
    if len(values.get("MLFLOW_AUTH_ADMIN_PASSWORD", "")) < MIN_PASSWORD:
        raise ProfileError("MLFLOW_AUTH_ADMIN_PASSWORD missing or shorter than 12 characters")
    if not values.get("MLFLOW_FLASK_SERVER_SECRET_KEY"):
        raise ProfileError("MLFLOW_FLASK_SERVER_SECRET_KEY missing")
    admin_password = values["MLFLOW_AUTH_ADMIN_PASSWORD"]
    if admin_password.casefold().startswith("password") and admin_password[8:].isdecimal():
        raise ProfileError("predictable default admin password is not allowed")


def server_argv(profile: Profile, mlflow_bin: str = "mlflow") -> list[str]:
    """Command line of the authenticated loopback server for this profile."""
    return [
        mlflow_bin,
        "server",
        "--app-name",
        AUTH_APP,
        "--host",
        "127.0.0.1",
        "--port",
        str(profile.port),
        "--workers",
        "1",
        "--backend-store-uri",
        profile.store_uri,
        "--artifacts-destination",
        str(profile.artifacts),
        "--serve-artifacts",
    ]


def server_env(profile: Profile) -> dict[str, str]:
    """Environment for the server process: secrets plus config path, telemetry off, no OTEL."""
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(read_secrets(profile))
    env.update(
        {
            "MLFLOW_AUTH_CONFIG_PATH": str(profile.auth_ini),
            # Native workspace scoping: creating anything needs a workspace-wide USE/MANAGE
            # grant, which students never get; per-experiment READ grants keep working.
            "MLFLOW_ENABLE_WORKSPACES": "true",
            "MLFLOW_DISABLE_TELEMETRY": "true",
            "MLFLOW_DISABLE_AGENT_HINT": "1",
        }
    )
    return env


def main() -> None:
    """Start exactly the same authenticated configuration exercised by integration tests."""
    profile = load_profile(Path(sys.argv[1]))
    executable = str(Path(sys.executable).parent / "mlflow")
    os.execvpe(executable, server_argv(profile, executable), server_env(profile))


if __name__ == "__main__":
    main()
