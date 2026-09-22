# Developer guide

Use versions and commands in the README. Python imports from `server/`;
`PYTHONPATH=server` is needed for direct Uvicorn execution. Pytest sets this path in
`pyproject.toml`. Environments and dependencies are local.

## Edit cycle

Start Compose databases and the loopback API. Restart Python after edits, or use
local Uvicorn `--reload`. `npm --prefix web run dev` starts Vite with the API proxy
in `web/vite.config.ts`. The integrated journey uses a compiled frontend served by
FastAPI. Rebuild and refresh the browser after frontend edits.

SQLAlchemy `create_all` initializes tables for this implementation; it does not
migrate existing columns. A schema change needs an explicit migration and data
preservation plan. Tests recreate only their own temporary databases.

## Coding conventions

Write straightforward typed Python and TypeScript. Keep domain logic independent
of provider SDKs and UI code. Target at most 300 lines per focused module and 50
per ordinary function. Avoid speculative factories, interfaces, plugin systems and
compatibility layers.

Public Python functions and classes use Google-style docstrings. Explain behaviour
and invariants; use `Args`, `Returns` and `Raises` for nontrivial boundaries.
Validate external inputs at boundaries. Write docs, code and errors in English;
retain the source language in quotations. Identify timezones in labels and keep
calculations, retrieved claims and model inferences separate.

## Verification

Run focused tests for affected behaviour, then required final checks once. Default
tests do not call paid providers. Cover ownership, original bytes, mappings,
concurrent corrections, revoked sessions, unsafe rendering and budget admission.
Synthetic fixtures are not field evidence.

Use `/api/docs` or `/api/openapi.json` for the live schema. Browser verification
should create a synthetic account, company and machine; upload exact fixtures; map
CSV; ask within an authorized budget; inspect citations and originals; correct
context; and check supersession. Also test cross-account denial for sources and
conversations. A build alone does not verify this journey.

## Dependency and model updates

Read primary upstream documentation and check official registries before changing
an API dependency. Pin compatible versions, preserve lockfiles, and record the
source, date and compatibility result. Context7 snippets are supporting material,
not a release or compatibility check.

A new model needs current API/pricing docs, bounded request/usage handling, spend
reservation, focused tests and an authorized real canary. Catalogue entries do not
prove access or task quality. Never add hidden retries or expand budget during an
upgrade. Preserve upstream warnings and failed checks.
