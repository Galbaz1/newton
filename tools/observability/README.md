# Optional MLflow

Run experiment tracking on your own approved infrastructure. Newton writes a
local, sanitized metadata outbox; this tool explicitly synchronizes it to a
configured MLflow service. Nothing in the main application connects automatically
to a project owner's server. Tenant originals and full model prompts are excluded
from the snapshot schema; identifiers and metrics still deserve private handling.

## Install an authenticated service

From this directory, install the separate locked environment. The launcher also
requires `tmux`. Use an absolute path outside the source tree for runtime storage.

```sh
uv sync --frozen --group dev
uv run python -m newton_observability.accounts init-profile \
  --runtime /absolute/path/to/teaching-runtime --name teaching --port 18768
./run-service.sh /absolute/path/to/teaching-runtime
```

Each profile owns its auth database, backend database, artifacts and generated
0600 secrets. Services bind loopback only. Use separate profiles and storage for
private research and teaching; never copy customer runs into teaching. A remote
connection requires an operator-approved encrypted tunnel. Basic authentication
must not cross a LAN or public network in plaintext.

## Approve access

Only the bootstrap owner created by `init-profile` admits accounts. There is no
self-registration. The owner explicitly selects one of two assignable roles:

| Role | Access inside that service |
| --- | --- |
| `student` | Read explicitly selected experiments and their artifacts |
| `admin` | Create/manage experiments and runs; no account administration |

An assigned admin is not MLflow's platform administrator. Neither role grants host,
shell, SSH, private-profile or Newton-company access. Anyone with the underlying
OS account can read its files; profile separation is not process sandboxing.

Set `NEWTON_ACCOUNT_PASSWORD` through your secret manager, then run:

```sh
uv run python -m newton_observability.accounts approve \
  --runtime /absolute/path/to/teaching-runtime --account student-name \
  --role student --experiment EXPERIMENT_ID --actor owner-name
```

Use `--role admin` without `--experiment` to grant the second role. Re-approval
replaces managed grants rather than accumulating them. Use the `revoke` command
with the same runtime/account/actor to remove access. Decisions are privately
audited without recording passwords. Keep bootstrap credentials with the operator.

## Synchronize selected metadata

Set `MLFLOW_TRACKING_USERNAME` and `MLFLOW_TRACKING_PASSWORD` in the environment.
Choose a loopback service or your approved local tunnel, then explicitly send a
selected outbox:

```sh
uv run python -m newton_observability.cli \
  --tracking-uri http://127.0.0.1:18768 \
  --snapshots /absolute/path/to/approved/outbox \
  --state /absolute/path/to/private/sync-state.json --once
```

The synchronizer validates snapshots, avoids duplicating existing runs and reports
rejected records. A teaching service should receive synthetic teaching runs only.
The service uses pinned MLflow workspace permissions; that upstream feature is
experimental, so re-run the access tests when updating MLflow.

```sh
uv run pytest
```

The tests use disposable local HTTP services and synthetic accounts. They cover
anonymous denial, selected student reads, denied writes, admin scope, revocation
and separation between profiles. No existing server or account is needed.
