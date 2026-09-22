"""Contract and resource-bound tests using a deterministic fake encoder only."""
import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import encoder_service as service


class _Fake:
    def __init__(self):
        self.calls = []
        self.result = np.arange(1, 961, dtype=np.float32).reshape(3, 320)
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = False

    def encode_query(self, items, **kwargs):
        self.calls.append(items[0])
        self.entered.set()
        if self.block:
            assert self.release.wait(5)
        return [self.result]

    def encode_document(self, items, **kwargs):
        assert items[0].mode == "RGB"
        return self.encode_query(items, **kwargs)


@pytest.fixture
def client():
    """Yield a lifespan-started client and its fake encoder."""
    fake = _Fake()
    with TestClient(service.create_app(lambda: fake), base_url="http://localhost") as http:
        yield http, fake


def _png(mode="RGBA", **kwargs):
    buffer = io.BytesIO()
    Image.new(mode, (16, 16)).save(buffer, format="PNG", **kwargs)
    return buffer.getvalue()


def _code(response, status, code):
    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}


def test_health_lifecycle():
    """Readiness is false before load, true after load, false after shutdown."""
    app = service.create_app(_Fake)
    http = TestClient(app, base_url="http://127.0.0.1")
    _code(http.get("/health"), 503, "not_ready")
    _code(http.post("/encode/query", json={"text": "hello"}), 503, "not_ready")
    with http:
        assert http.get("/health").json() == {
            "status": "ready", **service.META, "device": "mps", "max_pixels": 1080000}
    _code(http.get("/health"), 503, "not_ready")


def test_failed_load_is_sanitized():
    """A loader failure cannot publish readiness or disclose its exception."""
    def fail():
        raise ValueError("secret/path")
    app = service.create_app(fail)
    with pytest.raises(RuntimeError, match="^encoder_startup_failed$"):
        with TestClient(app):
            pass
    assert app.state.encoder is None


@pytest.mark.parametrize("path,payload", [
    ("/encode/query", {"json": {"text": "hello"}}),
    ("/encode/page", {"content": _png(), "headers": {"content-type": "image/png"}}),
])
def test_normalized_finite_320d(client, path, payload):
    """Both routes return finite unit rows and exactly the response contract."""
    http, fake = client
    response = http.post(path, **payload)
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"model", "revision", "dimensions", "shape", "vectors", "seconds"}
    assert {k: result[k] for k in service.META} == service.META
    matrix = np.asarray(result["vectors"], dtype=np.float32)
    assert matrix.shape == (3, 320) and result["shape"] == [3, 320]
    assert np.isfinite(matrix).all()
    np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-6)
    assert isinstance(result["seconds"], float) and result["seconds"] >= 0
    assert len(fake.calls) == 1


@pytest.mark.parametrize("body", [b"", b"not png", _png()[:-10]])
def test_invalid_png(client, body):
    """Malformed and truncated PNGs fail without reaching the encoder."""
    http, fake = client
    _code(http.post("/encode/page", content=body, headers={"content-type": "image/png"}),
          400, "invalid_png")
    assert not fake.calls


def test_multiframe_and_source_pixel_limits(client):
    """APNG and oversized source dimensions are rejected before pixel decoding."""
    import struct
    import zlib
    http, fake = client
    frame = Image.new("RGBA", (16, 16), "red")
    animated = _png(save_all=True, append_images=[frame])
    source = bytearray(_png())
    source[16:24] = struct.pack(">II", 4001, 4000)
    source[29:33] = struct.pack(">I", zlib.crc32(source[12:29]))
    for body in [animated, bytes(source)]:
        _code(http.post("/encode/page", content=body, headers={"content-type": "image/png"}),
              400, "invalid_png")
    assert not fake.calls


@pytest.mark.parametrize("payload", [
    {"text": ""}, {"text": " "}, {"text": "a" * 1501}, {"text": 1}, {},
    {"text": "hello", "url": "https://example.com"}, [],
])
def test_invalid_query(client, payload):
    """Queries enforce schema and character bounds without echoing input."""
    http, fake = client
    _code(http.post("/encode/query", json=payload), 422, "invalid_query")
    assert not fake.calls


def test_query_boundary_and_malformed_json(client):
    """The character maximum accepts multibyte text and rejects malformed JSON."""
    http, _ = client
    assert http.post("/encode/query", json={"text": "😀" * 1500}).status_code == 200
    _code(http.post("/encode/query", content=b'{"text":',
                    headers={"content-type": "application/json"}), 422, "invalid_query")


@pytest.mark.parametrize("path", ["/encode/page", "/encode/query"])
def test_declared_oversized_body(client, path):
    """Oversized content lengths are refused before payload parsing."""
    http, fake = client
    _code(http.post(path, content=b"x", headers={
        "content-length": str(service.LIMITS[path] + 1)}), 413, "body_too_large")
    assert not fake.calls


@pytest.mark.parametrize("declared", [False, True])
def test_streaming_body_bound(declared):
    """Chunked and falsely small declared bodies stop reading at the size cap."""
    async def run():
        reads, sent = 0, []
        async def downstream(scope, receive, send):
            pytest.fail("Oversized body reached parser")
        async def receive():
            nonlocal reads
            reads += 1
            return {"type": "http.request", "body": b"x" * 8193, "more_body": True}
        async def send(message):
            sent.append(message)
        headers = [(b"host", b"localhost")]
        if declared:
            headers.append((b"content-length", b"1"))
        await service._Boundary(downstream)(
            {"type": "http", "path": "/encode/query", "headers": headers}, receive, send)
        assert reads == 2 and sent[0]["status"] == 413
    asyncio.run(run())


@pytest.mark.parametrize("headers,status,code", [
    ({"host": "foreign.example"}, 400, "invalid_host"),
    ({"host": "localhost.evil"}, 400, "invalid_host"),
    ({"origin": "http://localhost"}, 403, "origin_forbidden"),
    ({"origin": "null"}, 403, "origin_forbidden"),
])
def test_host_origin(client, headers, status, code):
    """Foreign hosts and every Origin value are rejected."""
    _code(client[0].get("/health", headers=headers), status, code)


def test_busy_without_queue_and_health_responsive(client):
    """A running fake inference makes a concurrent request immediately busy."""
    http, fake = client
    fake.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(http.post, "/encode/query", json={"text": "first"})
        assert fake.entered.wait(2)
        try:
            _code(http.post("/encode/query", json={"text": "second"}), 409, "busy")
            assert http.get("/health").status_code == 200
        finally:
            fake.release.set()
        assert first.result(timeout=5).status_code == 200
    assert len(fake.calls) == 1


@pytest.mark.parametrize("shape,value", [
    ((1, 319), 1), ((0, 320), 1), ((513, 320), 1), ((1, 320), 0),
    ((1, 320), float("nan")), ((1, 320), float("inf")),
])
def test_bad_model_output_releases_lock(client, shape, value):
    """Invalid output fails closed and the next inference can still run."""
    http, fake = client
    fake.result = np.full(shape, value, dtype=np.float32)
    _code(http.post("/encode/query", json={"text": "hello"}), 500, "encoding_failed")
    fake.result = np.ones((1, 320), dtype=np.float32)
    assert http.post("/encode/query", json={"text": "hello"}).status_code == 200


def test_page_row_limit(client):
    """Page output allows 2,048 rows and rejects 2,049 rows."""
    http, fake = client
    for count, status in [(2048, 200), (2049, 500)]:
        fake.result = np.ones((count, 320), dtype=np.float32)
        assert http.post("/encode/page", content=_png(),
                         headers={"content-type": "image/png"}).status_code == status


def test_fixed_protocol_errors(client):
    """Unsupported inputs and missing routes return fixed structured errors."""
    http, _ = client
    _code(http.post("/encode/page", json={"path": "/secret"}), 415, "unsupported_media_type")
    _code(http.get("/missing"), 404, "not_found")
    _code(http.get("/encode/query"), 405, "method_not_allowed")
    _code(http.post("/encode/query", content=b"x", headers={"content-encoding": "gzip"}),
          415, "unsupported_media_type")


def test_loader_settings_and_validation(monkeypatch, tmp_path):
    """A stubbed native constructor receives the exact offline MPS settings."""
    import sys
    from types import SimpleNamespace
    calls = {}
    model = SimpleNamespace(eval=lambda: calls.update(evaluated=True))
    torch = SimpleNamespace(bfloat16="bf16", backends=SimpleNamespace(
        mps=SimpleNamespace(is_available=lambda: True)),
        set_num_threads=lambda n: calls.update(threads=n),
        set_num_interop_threads=lambda n: calls.update(interop=n))
    def constructor(directory, **kwargs):
        calls.update(directory=directory, kwargs=kwargs)
        return model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(MultiVectorEncoder=constructor))
    monkeypatch.setattr(service.hashlib, "sha256", lambda data: SimpleNamespace(
        hexdigest=lambda: "9c8600fb5c9034d2881ff37228a37cdbcee7aa178ff8393b369351d62f4c2842"))
    template = tmp_path / "additional_chat_templates"
    template.mkdir()
    (template / "sentence_transformers.jinja").write_bytes(b"synthetic template")
    monkeypatch.setenv("NEWTON_ENCODER_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_validate_model", lambda *args: calls.update(validated=args))
    assert service._load_model() is model
    assert calls["threads"] == 8 and calls["interop"] == 1 and calls["evaluated"]
    assert calls["validated"] == (model, tmp_path, torch)
    assert calls["kwargs"] == {
        "device": "mps", "revision": service.REVISION, "token": False,
        "trust_remote_code": False, "local_files_only": True,
        "model_kwargs": {"dtype": "bf16", "attn_implementation": "eager", "use_safetensors": True},
        "processor_kwargs": {"min_pixels": 1024, "max_pixels": 1080000}}


def test_cancelled_caller_does_not_release_inference_lock():
    """Cancellation leaves the lock owned by the worker until it completes."""
    import anyio
    from types import SimpleNamespace
    from starlette.requests import Request
    async def run():
        fake = _Fake()
        fake.block = True
        state = SimpleNamespace(encoder=fake, lock=threading.Lock(), limiter=anyio.CapacityLimiter(1))
        async def receive():
            return {"type": "http.request", "body": b'{"text":"hello"}', "more_body": False}
        request = Request({"type": "http", "path": "/encode/query", "scheme": "http",
                           "server": ("localhost", 80), "query_string": b"",
                           "headers": [(b"content-type", b"application/json")],
                           "app": SimpleNamespace(state=state)}, receive)
        task = asyncio.create_task(service._encode(request))
        for _ in range(200):
            if fake.entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert fake.entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.lock.locked()
        fake.release.set()
        for _ in range(200):
            if not state.lock.locked():
                break
            await asyncio.sleep(0.005)
        assert not state.lock.locked()
    asyncio.run(run())
