"""Provider boundary tests exercise accounting, request limits and failure semantics."""

import json

import httpx2
import pytest
from newton import budget, providers
from newton.config import settings


@pytest.fixture
def setup_provider(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"ceiling": 2, "paid_attempts": []}))
    monkeypatch.setattr(settings, "budget_path", path)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    return path


def test_answer_disables_provider_storage_and_bounds_reasoning(setup_provider, monkeypatch):
    captured = []

    def post(url, headers, json, timeout):
        captured.append(json)
        return httpx2.Response(
            200,
            request=httpx2.Request("POST", url),
            json={
                "status": "completed",
                "usage": {"input_tokens": 20, "output_tokens": 30},
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "Fact [E1]"}]}
                ],
            },
        )

    monkeypatch.setattr(providers.httpx2, "post", post)
    text, usage = providers.answer("Instructions", "Evidence", "gpt-6-astra")
    assert text == "Fact [E1]"
    assert captured[0]["store"] is False
    assert captured[0]["max_output_tokens"] == providers.MAX_OUTPUT
    assert "tools" not in captured[0]
    assert usage["output_tokens"] == 30
    assert budget.summary()["reserved_eur"] == 0


def test_timeout_has_one_attempt_and_retains_budget(setup_provider, monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise httpx2.ReadTimeout("network timeout")

    monkeypatch.setattr(providers.httpx2, "post", fail)
    with pytest.raises(providers.ProviderError, match="no automatic retry"):
        providers.answer("Instructions", "Evidence", "gpt-6-astra")
    assert len(calls) == 1
    assert budget.summary()["reserved_eur"] > 0


def test_gemini_counts_thinking_in_billed_output(setup_provider, monkeypatch):
    monkeypatch.setattr(
        providers.httpx2,
        "post",
        lambda url, **kwargs: httpx2.Response(
            200,
            request=httpx2.Request("POST", url),
            json={
                "usageMetadata": {
                    "promptTokenCount": 30,
                    "totalTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 50,
                },
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "internal", "thought": True},
                                {"text": "Visible answer"},
                            ]
                        },
                    }
                ],
            },
        ),
    )
    text, usage = providers.answer("Instructions", "Evidence", "gemini-3.8-flash")
    assert text == "Visible answer"
    assert usage["output_tokens"] == 70


def test_missing_usage_never_releases_charge(setup_provider, monkeypatch):
    monkeypatch.setattr(
        providers.httpx2,
        "post",
        lambda url, **kwargs: httpx2.Response(
            200, request=httpx2.Request("POST", url), json={"status": "completed", "output": []}
        ),
    )
    with pytest.raises(providers.ProviderError, match="omitted usage"):
        providers.answer("Instructions", "Evidence", "gpt-6-astra")
    assert budget.summary()["reserved_eur"] > 0


@pytest.mark.parametrize(
    "model,body",
    [
        (
            "gpt-6-astra",
            {
                "status": "completed",
                "usage": {"input_tokens": 20, "output_tokens": 30},
                "output": [{"type": "message", "content": [{"type": "output_text"}]}],
            },
        ),
        (
            "gemini-3.8-flash",
            {"usageMetadata": {"promptTokenCount": 20, "totalTokenCount": 50}, "candidates": []},
        ),
    ],
)
def test_malformed_answer_records_usage_and_raises_provider_error(
    setup_provider, monkeypatch, model, body
):
    monkeypatch.setattr(providers, "_post", lambda *args: body)
    with pytest.raises(providers.ProviderError, match="format was invalid"):
        providers.answer("system", "prompt", model)
    assert budget.summary()["spent_eur"] > 0
    assert budget.summary()["reserved_eur"] == 0


def test_malformed_embedding_records_usage_and_raises_provider_error(setup_provider, monkeypatch):
    monkeypatch.setattr(
        providers,
        "_post",
        lambda *args: {
            "usage": {"total_tokens": 20},
            "data": [{"index": 0}],
        },
    )
    with pytest.raises(providers.ProviderError, match="format was invalid"):
        providers.embed(["Synthetic evidence"])
    assert budget.summary()["spent_eur"] > 0
    assert budget.summary()["reserved_eur"] == 0
