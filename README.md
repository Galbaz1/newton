# Newton

Newton is a local workbench for investigating industrial machines. It keeps
company context, original source files, investigations, citations and corrections
in one application.

Newton is developed as an academic, non-commercial project. Its source code is
released under the [MIT License](LICENSE), which permits commercial use.
Hogeschool van Amsterdam (HvA) holds the copyright. Maker attribution: Wonder
Why AI — Fausto Albers; see [AUTHORS.md](AUTHORS.md). Newton does not control
machinery or certify diagnoses, components or safe operation.

## Run locally

Install Docker with Compose, Python **3.14.7**, Node **26.9.0**, and `uv`
(lock generation used **0.12.17**). Repository files pin the Python, Node,
container and application dependencies.

```sh
uv sync --frozen --group dev
uv run python scripts/setup_local.py
docker compose up -d
npm --prefix web ci
npm --prefix web run build
PYTHONPATH=server uv run uvicorn newton.main:app --host 127.0.0.1 --port 18765
```

Open **http://127.0.0.1:18765/** and create a local account. The API schema is
available at `/api/docs`; `/api/health` reports service status. Use Ctrl+C to
stop the app and `docker compose stop` to stop the databases without deleting
their volumes.

Setup creates private service credentials in `.env` and leaves provider keys
unset. Originals are stored in `.runtime/data`; PostgreSQL and Weaviate use
separate Docker volumes. Services bind to loopback. Read
[configuration](docs/configuration.md) before using real material.

## First investigation

1. Create a company and machine, then upload original manuals, images, text or
   CSV observations. You can also use Autonomous onboarding with a company name,
   an optional public website and multiple files.
2. Check the source states, proposed mappings and starter questions. PDF, text,
   image, CSV and annotation inputs retain their original bytes and SHA-256
   identities.
3. Open a starter question or create an investigation. Map CSV timestamps,
   values and units where required.
4. Select a configured model and submit a question. Newton retrieves checked
   document evidence and builds deterministic summaries from mapped measurements.
5. Inspect citations, sources and charts. Correct a location, part, time period
   or assumption when necessary. The earlier answer remains visible as
   superseded evidence.

Autonomous onboarding and model answers need provider credentials and an explicit API budget.
Text retrieval uses OpenAI embeddings, including when Gemini provides an answer.
The optional private ColQwen encoder adds visual page retrieval. Source material
sent to a selected provider leaves the computer for inference.

See [onboarding](docs/onboarding.md) for source states, corrections and the
local investigation flow.

## Develop and verify

```sh
uv run pytest
uv run ruff check server tests scripts
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

Backend tests use temporary SQLite databases, temporary files and mocked paid
providers. They cover ownership, source bytes, CSV validation, corrections,
session revocation and budget admission. They do not replace checks against the
configured PostgreSQL, Weaviate and browser journey. Read the
[developer guide](docs/development.md), [architecture](docs/architecture.md), and
[contributing guide](CONTRIBUTING.md).

## Private data

Keep supplied documents, credentials and runtime data outside source control.
The [distribution guide](docs/distribution.md) describes the source package and
dependency notices.
