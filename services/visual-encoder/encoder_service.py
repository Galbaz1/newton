"""Pinned offline visual encoder; launch only through this module's main()."""
import os

for _key, _value in {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "TOKENIZERS_PARALLELISM": "false", "PYTORCH_ENABLE_MPS_FALLBACK": "0",
    "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8",
    "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1",
}.items():
    os.environ[_key] = _value

import io
import hashlib
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import numpy as np
from fastapi import FastAPI, Request
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

MODEL = "athrael-soju/colqwen3.5-4.5B-v3"
REVISION = "c4ea4b92ff3322d68bfd6c65e492c69d0176f910"
META = {"model": MODEL, "revision": REVISION, "dimensions": 320}
LIMITS = {"/encode/query": 16384, "/encode/page": 8 * 1024**2}


class Query(BaseModel):
    """Strict bounded query payload.

    Attributes:
        text: Nonempty text of at most 1,500 Unicode characters.
    """
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=1500)


def _error(status, code):
    return JSONResponse({"error": {"code": code}}, status_code=status)


class _Boundary:
    def __init__(self, app):
        self.app = app
        self.admission = threading.BoundedSemaphore(16)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not self.admission.acquire(blocking=False):
            return await _error(409, "busy")(scope, receive, send)
        try:
            await self._bounded(scope, receive, send)
        finally:
            self.admission.release()

    async def _bounded(self, scope, receive, send):
        headers = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value)
        hosts = headers.get(b"host", [])
        host = hosts[0].split(b":")[0] if len(hosts) == 1 else b""
        if host not in (b"localhost", b"127.0.0.1"):
            return await _error(400, "invalid_host")(scope, receive, send)
        if b"origin" in headers:
            return await _error(403, "origin_forbidden")(scope, receive, send)
        limit = LIMITS.get(scope["path"], 0)
        lengths = headers.get(b"content-length", [])
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit()):
            return await _error(400, "invalid_length")(scope, receive, send)
        if lengths and (len(lengths[0]) > 10 or int(lengths[0]) > limit):
            return await _error(413, "body_too_large")(scope, receive, send)
        if b"content-encoding" in headers:
            return await _error(415, "unsupported_media_type")(scope, receive, send)
        body = bytearray()
        try:
            with anyio.fail_after(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        return await _error(413, "body_too_large")(scope, receive, send)
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await _error(408, "body_timeout")(scope, receive, send)
        if lengths and int(lengths[0]) != len(body):
            return await _error(400, "invalid_length")(scope, receive, send)
        async def replay():
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        await self.app(scope, replay, send)


def _validate_model(model, directory, torch):
    from safetensors.torch import load_file
    expected = load_file(str(directory / "1_Dense/model.safetensors"))
    if tuple(expected["linear.weight"].shape) != (320, 2560):
        raise ValueError("invalid_model")
    actual = model[1].state_dict()
    if actual.keys() != expected.keys() or model[1].linear.out_features != 320:
        raise ValueError("invalid_model")
    for key, value in expected.items():
        if not torch.equal(actual[key].detach().cpu(), value.to(actual[key].dtype)):
            raise ValueError("invalid_model")
    if [type(module).__name__ for module in model] != [
            "Transformer", "Dense", "Normalize", "MultiVectorMask"]:
        raise ValueError("invalid_model")
    if model[0].processor.image_processor.size != {"shortest_edge": 1024, "longest_edge": 1080000}:
        raise ValueError("invalid_processor")
    backbone = model[0].auto_model
    if backbone.config.text_config._attn_implementation != "eager":
        raise ValueError("invalid_attention")
    if backbone.config.text_config.is_causal is not False:
        raise ValueError("invalid_model")
    if model.similarity_fn_name != "maxsim":
        raise ValueError("invalid_model")
    if any(p.device.type != "mps" for p in model.parameters()):
        raise ValueError("invalid_device")
    if next(backbone.parameters()).dtype != torch.bfloat16:
        raise ValueError("invalid_dtype")


def _load_model():
    directory = Path(os.environ["NEWTON_ENCODER_MODEL_DIR"])
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("invalid_model_directory")
    template = directory / "additional_chat_templates/sentence_transformers.jinja"
    if hashlib.sha256(template.read_bytes()).hexdigest() != (
            "9c8600fb5c9034d2881ff37228a37cdbcee7aa178ff8393b369351d62f4c2842"):
        raise ValueError("invalid_template")
    import torch
    from sentence_transformers import MultiVectorEncoder
    if not torch.backends.mps.is_available():
        raise RuntimeError("mps_required")
    torch.set_num_threads(8)
    torch.set_num_interop_threads(1)
    model = MultiVectorEncoder(
        str(directory), device="mps", revision=REVISION, token=False,
        trust_remote_code=False, local_files_only=True,
        model_kwargs={"dtype": torch.bfloat16, "attn_implementation": "eager",
                      "use_safetensors": True},
        processor_kwargs={"min_pixels": 1024, "max_pixels": 1080000},
    )
    _validate_model(model, directory, torch)
    model.eval()
    return model


def _page(body):
    with Image.open(io.BytesIO(body), formats=["PNG"]) as image:
        if image.width * image.height > 16_000_000 or image.n_frames != 1:
            raise ValueError("invalid_image")
        image.verify()
    with Image.open(io.BytesIO(body), formats=["PNG"]) as image:
        return image.convert("RGB")


def _matrix(embedding, max_rows):
    if hasattr(embedding, "detach"):
        embedding = embedding.detach().float().cpu().numpy()
    matrix = np.asarray(embedding, dtype=np.float32)
    if (matrix.ndim != 2 or matrix.shape[1] != 320
            or not 1 <= matrix.shape[0] <= max_rows or not np.isfinite(matrix).all()):
        raise ValueError("invalid_vectors")
    # Float64 accumulation avoids overflow/underflow; exported components stay float32.
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("invalid_vectors")
    return (matrix / norms).astype(np.float32)


def _work(state, kind, payload):
    image = None
    started = time.perf_counter()
    try:
        if kind == "page":
            try:
                image = _page(payload)
            except Exception:
                return _error(400, "invalid_png")
        import torch
        encode = state.encoder.encode_document if image else state.encoder.encode_query
        with torch.inference_mode():
            result = encode([image if image else payload], batch_size=1,
                            show_progress_bar=False, convert_to_numpy=False)[0]
        matrix = _matrix(result, 2048 if image else 512)
        return JSONResponse({**META, "shape": list(matrix.shape),
                             "vectors": matrix.tolist(),
                             "seconds": time.perf_counter() - started})
    except Exception:
        return _error(500, "encoding_failed")
    finally:
        if image is not None:
            image.close()
        state.lock.release()


async def _encode(request: Request):
    state = request.app.state
    if state.encoder is None:
        return _error(503, "not_ready")
    kind = "page" if request.url.path.endswith("/page") else "query"
    content_type = request.headers.get("content-type", "").lower()
    expected = "image/png" if kind == "page" else "application/json"
    if content_type.split(";")[0].strip() != expected:
        return _error(415, "unsupported_media_type")
    payload = await request.body()
    if kind == "query":
        try:
            payload = Query.model_validate_json(payload).text
            if not payload.strip():
                raise ValueError("empty_query")
        except (ValidationError, ValueError):
            return _error(422, "invalid_query")
    if not state.lock.acquire(blocking=False):
        return _error(409, "busy")
    # The worker owns lock release, including if the client/task disappears.
    with anyio.CancelScope(shield=True):
        return await anyio.to_thread.run_sync(_work, state, kind, payload,
                                              limiter=state.limiter)


async def _health(request: Request):
    if request.app.state.encoder is None:
        return _error(503, "not_ready")
    return JSONResponse({"status": "ready", **META, "device": "mps", "max_pixels": 1080000})


async def _http_error(request, exc):
    return _error(exc.status_code, {404: "not_found", 405: "method_not_allowed"}.get(
        exc.status_code, "request_failed"))


async def _unexpected_error(request, exc):
    return _error(500, "internal_error")


def create_app(loader=_load_model):
    """Create the private service with a lifespan-loaded encoder.

    Args:
        loader: Zero-argument loader returning a validated encoder; tests inject a fake.

    Returns:
        A FastAPI application, initially unavailable until loading succeeds.
    """
    @asynccontextmanager
    async def lifespan(app):
        app.state.limiter = anyio.CapacityLimiter(1)
        try:
            app.state.encoder = await anyio.to_thread.run_sync(loader)
        except Exception:
            raise RuntimeError("encoder_startup_failed") from None
        try:
            yield
        finally:
            app.state.encoder = None
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.encoder, app.state.lock = None, threading.Lock()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.add_middleware(_Boundary)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
    app.add_api_route("/health", _health, methods=["GET"])
    app.add_api_route("/encode/query", _encode, methods=["POST"])
    app.add_api_route("/encode/page", _encode, methods=["POST"])
    return app


def main():
    """Run one loopback Uvicorn worker with bounded concurrency and no access logs."""
    import uvicorn
    logging.disable(logging.CRITICAL)
    uvicorn.run(create_app(), host="127.0.0.1", port=18766, workers=1,
                access_log=False, log_config=None, proxy_headers=False,
                backlog=16, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
