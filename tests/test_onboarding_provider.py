"""Offline Interactions contract: stateless history, usage and grounded profile claims."""

import json

import pytest
from newton import agent_provider, company_research
from newton.config import settings


def test_interactions_preserves_signed_steps_and_uses_stateless_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-synthetic")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    admitted, settled, payloads = [], [], []
    monkeypatch.setattr(
        agent_provider.budget, "reserve", lambda *args: admitted.append(args) or "attempt"
    )
    monkeypatch.setattr(agent_provider.budget, "settle", lambda *args: settled.append(args))
    response = {
        "status": "requires_action",
        "steps": [
            {"type": "thought", "signature": "synthetic-signature"},
            {"type": "function_call", "id": "call1", "name": "inspect", "arguments": {}},
        ],
        "usage": {"total_input_tokens": 12, "total_tokens": 30},
    }

    def post(url, headers, payload, attempt):
        payloads.append((headers, payload))
        return response

    monkeypatch.setattr(agent_provider, "_post", post)
    history = [agent_provider.user_step("quoted data")]
    result = agent_provider.interact("run", "policy", history, [])
    headers, payload = payloads[0]
    assert payload["store"] is False and payload["input"] == history
    assert headers["Api-Revision"] == "2026-05-20"
    assert result["steps"][0]["signature"] == "synthetic-signature"
    assert settled == [("attempt", 12, 18, 0)]
    assert admitted[0][0] == "gemini-3.8-flash"
    assert (
        json.loads((tmp_path / "onboarding/run/attempt.json").read_text())["steps"]
        == response["steps"]
    )


def test_invalid_usage_retains_response_and_reserve(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-synthetic")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(agent_provider.budget, "reserve", lambda *args: "unknown")
    failed = []
    monkeypatch.setattr(agent_provider.budget, "fail", lambda *args: failed.append(args))
    monkeypatch.setattr(agent_provider, "_post", lambda *args: {"status": "completed", "usage": {}})
    with pytest.raises(agent_provider.ProviderError, match="usage"):
        agent_provider.interact("run", "policy", [agent_provider.user_step("x")], [])
    assert failed == [("unknown", "invalid_interactions_usage")]
    assert (tmp_path / "onboarding/run/unknown.json").exists()


def test_search_queries_are_accounted_without_assuming_free_credit(monkeypatch):
    settled = []
    monkeypatch.setattr(agent_provider.budget, "settle", lambda *args: settled.append(args))
    response = {
        "usage": {"total_input_tokens": 10, "total_tokens": 30},
        "steps": [
            {"type": "google_search_call", "arguments": {"queries": ["company", "official site"]}}
        ],
    }
    receipt = agent_provider._record_usage(response, "search", True)
    assert receipt["search_queries"] == 2
    assert settled == [("search", 10, 20, 0.035)]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://localhost",
        "https://user:pass@example.com",
        "http://192.168.1.1",
        "http://a.local",
    ],
)
def test_research_rejects_private_or_credential_bearing_urls(url):
    with pytest.raises(ValueError):
        company_research.validate_public_url(url)


def test_company_profile_accepts_only_provider_annotated_claims(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    text = {
        "overview": "Synthetic company",
        "activities": [],
        "roles": [],
        "terminology": [],
        "identity_uncertain": False,
        "limitations": [],
        "claims": [
            {
                "text": "Confirmed tool source",
                "url": "https://example.com/official",
                "title": "Official",
            },
            {"text": "Invented citation", "url": "https://example.com/made-up", "title": "Wrong"},
        ],
    }
    grounded = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "Café builds tools.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/official",
                                "title": "Official",
                                "start_index": 0,
                                "end_index": len("Café builds tools.".encode()),
                            }
                        ],
                    }
                ],
            },
        ],
        "_receipt": {"attempt_id": "offline"},
    }
    structured = {
        "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": json.dumps(text)}]}
        ],
        "_receipt": {"attempt_id": "structure"},
    }
    responses = iter([grounded, structured])
    monkeypatch.setattr(agent_provider, "interact", lambda *args, **kwargs: next(responses))
    profile = company_research.research("run", "Synthetic", "")
    assert len(profile["claims"]) == 1
    assert profile["claims"][0]["retrieved_at"]
    assert profile["claims"][0]["text"] == "Café builds tools."
    assert profile["structure_receipt"]["attempt_id"] == "structure"


def test_plain_model_links_and_invalid_annotation_ranges_are_not_evidence():
    response = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "https://example.com invented",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "http://127.0.0.1",
                                "start_index": 0,
                                "end_index": 4,
                            },
                            {
                                "type": "url_citation",
                                "url": "https://example.com",
                                "start_index": -1,
                                "end_index": 3,
                            },
                        ],
                    }
                ],
            }
        ]
    }
    assert company_research.cited_sources(response) == []
