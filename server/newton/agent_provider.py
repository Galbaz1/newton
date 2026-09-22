"""Stateless Gemini Interactions calls with explicit budget and private receipts."""

import json
import os
import time

from . import budget
from .config import settings
from .providers import ProviderError, _post

MODEL = "gemini-3.8-flash"
MAX_OUTPUT = 8192
MAX_INPUT_BYTES = 180_000
SEARCH_FEE_EUR = 14 / 1000 * budget.EUR_MARGIN


def output_text(response: dict) -> str:
    """Read only documented model output text, excluding thoughts and tool content."""
    return "\n".join(
        part["text"]
        for step in response.get("steps", [])
        if step.get("type") == "model_output"
        for part in step.get("content", [])
        if part.get("type") == "text"
    )


def interact(
    run_id: str,
    system: str,
    history: list,
    tools: list,
    schema: dict | None = None,
    *,
    research: bool = False,
) -> dict:
    """Execute one bounded provider turn and retain the exact private response.

    Args:
        run_id: Locally generated UUID used only to group private receipts.
        system: Application-owned instructions, never source-provided instructions.
        history: Explicit input steps; Newton owns the conversation state.
        tools: Application-controlled tool declarations.
        schema: Optional validated structured final output schema.
        research: Admit Google Search charges and bounded retrieved context.

    Returns:
        Raw response including steps plus a local `_receipt` usage projection.

    Raises:
        ProviderError: HTTP/protocol failure; unknown usage keeps its full reserve.
        ValueError: Missing credential or oversized context.
        budget.BudgetExceeded: Shared authorized spending cap cannot admit the turn.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        raise ValueError("Gemini is not configured")
    payload = {
        "model": MODEL,
        "store": False,
        "system_instruction": system,
        "input": history,
        "tools": tools,
        "generation_config": {"max_output_tokens": MAX_OUTPUT, "thinking_level": "low"},
    }
    if schema:
        payload["response_format"] = {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        }
    size = len(json.dumps(payload, ensure_ascii=False).encode())
    if size > MAX_INPUT_BYTES:
        raise ValueError("Agent context exceeds its bounded input size")
    # Research may retrieve additional text. Reserve the complete model context and
    # 100 search queries; observed search usage is reconciled without free-tier credit.
    bound = 1_048_576 if research else size
    attempt = budget.reserve(
        MODEL,
        bound,
        MAX_OUTPUT,
        "onboarding_research" if research else "onboarding_agent",
        100 * SEARCH_FEE_EUR if research else 0,
    )
    started = time.monotonic()
    response = _post(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        {"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Api-Revision": "2026-05-20"},
        payload,
        attempt,
    )
    directory = settings.data_dir / "onboarding" / run_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{attempt}.json"
    path.write_text(json.dumps(response, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    receipt = _record_usage(response, attempt, research)
    receipt["seconds"] = round(time.monotonic() - started, 3)
    response["_receipt"] = receipt
    path.write_text(json.dumps(response, ensure_ascii=False, indent=2))
    if response.get("status") not in {"completed", "requires_action"}:
        raise ProviderError("Gemini did not complete its bounded turn; receipt retained")
    return response


def _record_usage(response: dict, attempt: str, research: bool) -> dict:
    usage = response.get("usage", {})
    incoming = usage.get("total_input_tokens")
    total = usage.get("total_tokens")
    outgoing = total - incoming if type(total) is int and type(incoming) is int else None
    if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
        budget.fail(attempt, "invalid_interactions_usage")
        raise ProviderError("Gemini omitted usage; reserve retained")
    searches = sum(
        len(s.get("arguments", {}).get("queries", []))
        for s in response.get("steps", [])
        if s.get("type") == "google_search_call"
    )
    fee = searches * SEARCH_FEE_EUR if research else 0
    budget.settle(attempt, incoming, outgoing, round(fee, 6))
    return {
        "attempt_id": attempt,
        "input_tokens": incoming,
        "output_tokens": outgoing,
        "search_queries": searches,
        "tool_fee_eur": round(fee, 6),
    }


def user_step(value: str | dict) -> dict:
    """Encode local context as quoted user data in the Interactions step schema."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"type": "user_input", "content": [{"type": "text", "text": text}]}
