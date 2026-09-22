# Optional visual encoder

A loopback FastAPI service providing page and query multi-vectors for Newton.
It requires Apple Silicon with MPS and its own Python environment. It contains no
model weights, tenant database or hosted-service access.

## Setup

Obtain the checkpoint `athrael-soju/colqwen3.5-4.5B-v3`, revision
`c4ea4b92ff3322d68bfd6c65e492c69d0176f910`, from its
[model repository](https://huggingface.co/athrael-soju/colqwen3.5-4.5B-v3).
Review its terms and retain the exact revision provenance. Model files are private
runtime resources, never source-control contents. The service does not download
weights implicitly or fall back to CPU inference.

From this directory:

```sh
uv sync --frozen --group dev
export NEWTON_ENCODER_MODEL_DIR=/absolute/path/to/your/verified/checkpoint
PYTHONDONTWRITEBYTECODE=1 uv run --frozen --no-sync python -B encoder_service.py
```

This launcher binds `127.0.0.1:18766`, with one worker. It checks the template,
projection weights, attention settings and MPS placement before reporting ready.
Do not substitute a public bind address or launch multiple model workers.

Configure Newton with `NEWTON_VISUAL_ENCODER_URL=http://127.0.0.1:18766`.
For your own approved remote host, use an authenticated SSH local forward to that
loopback port; Newton accepts only a loopback HTTP encoder URL. The service has
no application login and rejects browser Origin headers. Local processes can
still call it: the Newton core owns tenant authorization.

## API and tests

- `GET /health`: pinned model/revision/dimensions; 503 until ready.
- `POST /encode/query`: JSON `{"text":"your question"}`; bounded query token matrix.
- `POST /encode/page`: raw PNG bytes, at most 8 MiB; bounded page patch matrix.

Both encode routes return normalized 320-dimensional vectors and elapsed time.
No source cache, retrieval score or diagnosis is implemented here. Newton stores
the derived vectors in Weaviate and rechecks source identities before answering.

```sh
uv run pytest
```

Tests use mocked inference and synthetic images. Passing them does not establish
checkpoint quality or successful MPS operation on your hardware. Keep originals
and weights separate from the source distribution.
