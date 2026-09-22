"""Explicit per-account approval and revocation against one authenticated service.

Roles (MLflow 3.16.1 basic-auth RBAC with native workspaces enabled, verified in
``mlflow.server.auth`` and ``tests/test_access.py``):
  * ``student``: READ on exactly the experiments named by the operator (runs,
    metrics, traces, artifacts of those experiments); no workspace-wide grant,
    so no experiment/model/prompt/run creation and no user or role management.
  * ``admin``: the named workspace role ``newton-teaching-admin`` (workspace-wide
    USE so it can create; ``experiment`` wildcard MANAGE so it can read, write,
    delete, and see artifacts/traces of every experiment on this service). It is
    NOT MLflow ``is_admin``: it cannot create users, grant platform admin or admit
    anyone. Only the bootstrap owner (operator identity from ``secrets.env``,
    not an assignable role) holds ``is_admin`` and runs this tool.
Approval REPLACES the account's previous state: every resource grant and role
assignment is revoked first (creator grants included) and the admin flag is set
explicitly; an unknown grant shape aborts before anything is changed (fail closed).
Every decision is appended to the profile's audit log with the acting approver.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from mlflow.exceptions import MlflowException  # noqa: E402
from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST, ErrorCode  # noqa: E402
from mlflow.server.auth.client import AuthServiceClient  # noqa: E402
from mlflow.server.auth.routes import LIST_USER_PERMISSIONS  # noqa: E402
from mlflow.utils.validation import _validate_username  # noqa: E402

from .service import Profile, init_profile, load_profile, read_secrets  # noqa: E402

ROLES = ("student", "admin")
ACCOUNT_PASSWORD_ENV = "NEWTON_ACCOUNT_PASSWORD"
ADMIN_ROLE = "newton-teaching-admin"
WORKSPACE = "default"  # mlflow.utils.workspace_utils.DEFAULT_WORKSPACE_NAME
ADMIN_ROLE_PERMISSIONS = (("workspace", "*", "USE"), ("experiment", "*", "MANAGE"))


def _client(profile: Profile) -> AuthServiceClient:
    """Auth client acting as the profile's bootstrap admin; credentials stay in the process env."""
    values = read_secrets(profile)
    os.environ["MLFLOW_TRACKING_USERNAME"] = values["MLFLOW_AUTH_ADMIN_USERNAME"]
    os.environ["MLFLOW_TRACKING_PASSWORD"] = values["MLFLOW_AUTH_ADMIN_PASSWORD"]
    return AuthServiceClient(profile.tracking_uri)


def _audit(profile: Profile, **record: object) -> None:
    """Append one JSON line (actor, action, account, decision); never a password."""
    line = json.dumps({"at_ms": int(time.time() * 1000), "service": profile.name, **record}, sort_keys=True)
    with open(profile.audit_log, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    os.chmod(profile.audit_log, 0o600)


def _ensure_user(client: AuthServiceClient, account: str, password: str | None) -> bool:
    """Create the account if unknown; returns True when it was created."""
    try:
        client.get_user(account)
        return False
    except MlflowException as error:
        if error.error_code != ErrorCode.Name(RESOURCE_DOES_NOT_EXIST):
            raise  # auth failure, connection problem, ...: never mask it as "new user"
    if not password:
        raise SystemExit(f"{account} does not exist; provide {ACCOUNT_PASSWORD_ENV} to create it")
    client.create_user(account, password)
    return True


def _clear_grants(client: AuthServiceClient, account: str) -> list[dict]:
    """Revoke every resource grant and role of the account; returns what was removed.

    Rows come from the v3 ``users/permissions/list`` API. Only exact resource
    grants (``resource_pattern`` without wildcard) can be revoked one by one; a
    wildcard or workspace-tier row is not a shape this tool manages, so the
    transition is refused before any change is made.
    """
    rows = client._request(LIST_USER_PERMISSIONS, "GET", params={"username": account}).get("permissions", [])
    direct = [row for row in rows if row.get("role_name") != ADMIN_ROLE]
    for row in direct:
        if "*" in str(row.get("resource_pattern", "")) or row.get("resource_type") == "workspace":
            raise SystemExit(f"refusing role change for {account}: unmanaged grant {row}")
    for row in direct:
        client.revoke_user_permission(account, row["resource_type"], row["resource_pattern"])
    for role in client.list_user_roles(account):
        client.unassign_role(account, role.id)
    return rows


def _admin_role_id(client: AuthServiceClient) -> int:
    """Return the managed teaching-admin role, creating it once with its fixed permissions."""
    for role in client.list_roles(WORKSPACE):
        if role.name == ADMIN_ROLE:
            return role.id
    role = client.create_role(WORKSPACE, ADMIN_ROLE, "Newton: administer teaching experiments, never accounts")
    for resource_type, pattern, permission in ADMIN_ROLE_PERMISSIONS:
        client.add_role_permission(role.id, resource_type, pattern, permission)
    return role.id


def approve(profile: Profile, account: str, role: str, experiment_ids: list[str], actor: str) -> dict:
    """Grant exactly the requested role to one named account.

    Args:
        profile: Target service profile.
        account: Username; validated by MLflow's own username rule.
        role: ``student`` (needs ``experiment_ids``) or ``admin``.
        experiment_ids: Teaching experiments a student may read.
        actor: Human approver recorded in the audit line (not authenticated here).

    Returns:
        The audit record that was written.
    """
    _validate_username(account)
    if role not in ROLES:
        raise SystemExit(f"role must be one of {ROLES}")
    if role == "student" and not experiment_ids:
        raise SystemExit("student approval requires at least one --experiment id")
    if account == read_secrets(profile)["MLFLOW_AUTH_ADMIN_USERNAME"]:
        raise SystemExit("the bootstrap owner is the operator identity, not an assignable role")
    client = _client(profile)
    created = _ensure_user(client, account, os.environ.get(ACCOUNT_PASSWORD_ENV))
    removed = _clear_grants(client, account)
    client.update_user_admin(account, False)  # assignable roles never hold platform admin
    if role == "admin":
        client.assign_role(account, _admin_role_id(client))
    for experiment_id in experiment_ids if role == "student" else []:
        client.grant_user_permission(account, "experiment", experiment_id, "READ")
    record = {"action": "approve", "account": account, "role": role, "experiments": experiment_ids,
              "created": created, "revoked_grants": len(removed), "actor": actor, "decision": "granted"}
    _audit(profile, **record)
    return record


def revoke(profile: Profile, account: str, actor: str) -> dict:
    """Delete the account so every credential stops working immediately."""
    _validate_username(account)
    client = _client(profile)
    client.delete_user(account)
    record = {"action": "revoke", "account": account, "actor": actor, "decision": "revoked"}
    _audit(profile, **record)
    return record


def main(argv: list[str] | None = None) -> int:
    """CLI: ``init-profile``, ``approve`` and ``revoke``."""
    parser = argparse.ArgumentParser(prog="newton-observability-access")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-profile", help="create a fail-closed service profile")
    init.add_argument("--runtime", type=Path, required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--port", type=int, required=True)
    init.add_argument("--admin-username", default="newton-admin")
    for name in ("approve", "revoke"):
        command = sub.add_parser(name)
        command.add_argument("--runtime", type=Path, required=True)
        command.add_argument("--account", required=True)
        command.add_argument("--actor", required=True, help="who approved this (audit only)")
        if name == "approve":
            command.add_argument("--role", choices=ROLES, required=True)
            command.add_argument("--experiment", action="append", default=[], help="experiment id a student may read")
    args = parser.parse_args(argv)
    if args.command == "init-profile":
        profile = init_profile(args.runtime, args.name, args.port, args.admin_username)
        print(f"profile {profile.name} at {profile.root} port {profile.port}")
        return 0
    profile = load_profile(args.runtime)
    record = approve(profile, args.account, args.role, args.experiment, args.actor) if args.command == "approve" \
        else revoke(profile, args.account, args.actor)
    print(json.dumps(record, sort_keys=True), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
