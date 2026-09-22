"""Visual evidence crosses model, source and provider boundaries with explicit identity."""

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from newton import provider_images, providers, visual_encoder, visual_retrieval
from newton.config import settings
from PIL import Image


def png(size=(20, 16)):
    stream = io.BytesIO()
    Image.new("RGB", size, "blue").save(stream, format="PNG")
    return stream.getvalue()


def matrix():
    return {
        "model": visual_encoder.MODEL,
        "revision": visual_encoder.REVISION,
        "dimensions": 320,
        "shape": [1, 320],
        "vectors": [[1.0] + [0.0] * 319],
    }


@pytest.mark.parametrize("mutation", ["revision", "dimensions", "shape", "nan", "norm"])
def test_encoder_rejects_wrong_identity_or_vectors(monkeypatch, mutation):
    result = matrix()
    if mutation in {"revision", "dimensions", "shape"}:
        result[mutation] = "wrong"
    elif mutation == "nan":
        result["vectors"][0][0] = float("nan")
    else:
        result["vectors"][0][0] = 2.0
    monkeypatch.setattr(visual_encoder, "_request", lambda *args, **kwargs: result)
    with pytest.raises(ValueError):
        visual_encoder.encode_query("A synthetic question")


def test_encoder_restricts_route_to_loopback(monkeypatch):
    for url in ["https://example.test", "http://127.0.0.1@evil.test", "http://localhost/path"]:
        monkeypatch.setattr(settings, "visual_encoder_url", url)
        with pytest.raises(ValueError, match="loopback"):
            visual_encoder._base_url()


def test_page_view_is_bounded_and_original_remains_unchanged():
    original = png((1800, 900))
    before = hashlib.sha256(original).hexdigest()
    rendered = visual_encoder.prepare_page(original)
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.size == (1600, 800) and image.mode == "RGB"
    assert hashlib.sha256(original).hexdigest() == before


@pytest.mark.parametrize("model", ["gpt-6-astra", "gemini-3.8-flash"])
def test_provider_images_keep_citation_and_conservative_budget(tmp_path, monkeypatch, model):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"ceiling": 5, "paid_attempts": []}))
    monkeypatch.setattr(settings, "budget_path", ledger)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    requests = []

    def post(url, headers, payload, attempt):
        requests.append(payload)
        if model.startswith("gemini"):
            return {
                "usageMetadata": {"promptTokenCount": 1100, "totalTokenCount": 1105},
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "Blue page [E3]"}]}}
                ],
            }
        return {
            "status": "completed",
            "usage": {"input_tokens": 1100, "output_tokens": 5},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Blue page [E3]"}]}
            ],
        }

    monkeypatch.setattr(providers, "_post", post)
    text, usage = providers.answer("system", "evidence", model, (("E3", png()),))
    assert text == "Blue page [E3]" and usage["input_tokens"] == 1100
    request = requests[0]
    parts = (
        request["contents"][0]["parts"]
        if model.startswith("gemini")
        else request["input"][0]["content"]
    )
    assert "[E3]" in parts[1]["text"]
    image = parts[2]
    if model.startswith("gemini"):
        assert image["inlineData"]["mimeType"] == "image/png"
        assert image["mediaResolution"]["level"] == "MEDIA_RESOLUTION_HIGH"
    else:
        assert image["image_url"].startswith("data:image/png;base64,")
        assert image["detail"] == "high"
    charge = json.loads(ledger.read_text())["paid_attempts"][0]
    assert charge["input_token_bound"] >= provider_images.IMAGE_TOKEN_BOUND + 1024
    assert charge["status"] == "complete"


def test_image_limit_rejected_before_paid_admission(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(settings, "budget_path", tmp_path / "absent-ledger.json")
    with pytest.raises(ValueError, match="three page images"):
        providers.answer("system", "prompt", "gpt-6-astra", tuple(("E1", png()) for _ in range(4)))


@pytest.mark.parametrize("fault", ["company", "machine", "version", "page", "deleted"])
def test_visual_candidate_rechecked_before_reading_original(monkeypatch, fault):
    source = SimpleNamespace(
        id="s",
        company_id="c",
        data_class="original",
        machine_id="m",
        version=2,
        status="needs_text",
        kind="image",
        media_type="image/png",
    )
    page = SimpleNamespace(id="p", source_id="s", number=1)
    props = {"source_id": "s", "page_id": "p", "source_version": 2, "page_number": 1}
    if fault == "company":
        source.company_id = "other"
    if fault == "machine":
        source.machine_id = "other"
    if fault == "version":
        props["source_version"] = 1
    if fault == "page":
        page.source_id = "foreign-source"
    if fault == "deleted":
        source = None
    db = SimpleNamespace(get=lambda model, key, **kw: source if key == "s" else page)
    monkeypatch.setattr(visual_retrieval, "_render", lambda *args: pytest.fail("unauthorized read"))
    assert visual_retrieval._evidence(db, [SimpleNamespace(properties=props)], "c", "m") == ([], [])


def test_visual_index_reuses_exact_generation_and_purges_old(monkeypatch):
    from test_retrieval import FakeCollection

    collection = FakeCollection()
    page, source = (
        SimpleNamespace(id="p", number=1),
        SimpleNamespace(id="s", version=1, machine_id="m", data_class="original"),
    )
    calls = []
    monkeypatch.setattr(visual_retrieval, "_render", lambda *args: png())
    monkeypatch.setattr(visual_encoder, "encode_page", lambda data: calls.append(data) or [[1.0]])
    deadline = datetime.now(UTC) + timedelta(minutes=10)
    visual_retrieval._sync(collection, [(page, source)], "m", deadline)
    visual_retrieval._sync(collection, [(page, source)], "m", deadline)
    assert len(calls) == 1
    source.version = 2
    visual_retrieval._sync(collection, [(page, source)], "m", deadline)
    assert len(calls) == 2 and len(collection.objects) == 1
    assert next(iter(collection.objects.values()))["source_version"] == 2
    visual_retrieval._sync(collection, [], "m", deadline)
    assert collection.objects == {}
