"""Bounded provider calls; no tool execution, hidden retries or provider-owned state."""

import os
import time

import httpx2

from newton import budget, provider_images, provider_pdfs

MODELS = {
    "gpt-5.6-sol": ("GPT-5.6 Sol", "OPENAI_API_KEY"),
    "gpt-6-astra": ("GPT-6 Astra · cruciale moeilijke vraag", "OPENAI_API_KEY"),
    "gemini-3.8-flash": ("Gemini 3.8 Flash", "GEMINI_API_KEY"),
}
MAX_OUTPUT = 4096


class ProviderError(RuntimeError):
    """A bounded provider request failed or returned no usable answer."""


def available_models() -> list[dict]:
    """List configured models; credential presence is not a successful inference."""
    return [
        {"id": model, "label": label, "available": bool(os.environ.get(key))}
        for model, (label, key) in MODELS.items()
    ]


def _post(url: str, headers: dict, payload: dict, attempt: str) -> dict:
    try:
        response = httpx2.post(url, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Provider response must be an object.")
        return data
    except (httpx2.HTTPError, ValueError) as error:
        category = type(error).__name__
        if isinstance(error, httpx2.HTTPStatusError):
            category = f"HTTP{error.response.status_code}"
        budget.fail(attempt, category)
        raise ProviderError(f"Provider request failed ({category}); no automatic retry.") from error


def _settle(attempt: str, incoming, outgoing) -> None:
    if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
        budget.fail(attempt, "invalid_usage")
        raise ProviderError("Provider omitted usage or returned invalid usage; reserve retained.")
    try:
        budget.settle(attempt, incoming, outgoing)
    except ValueError as error:
        budget.fail(attempt, "usage_admission_mismatch")
        raise ProviderError(
            "Provider usage did not match admission; check the budget ledger."
        ) from error


def _openai(system: str, parts: list, model: str, attempt: str) -> tuple[str, dict]:
    data = _post(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        {
            "model": model,
            "instructions": system,
            "input": [{"role": "user", "content": parts}],
            "store": False,
            "reasoning": {"effort": "low"},
            "max_output_tokens": MAX_OUTPUT,
        },
        attempt,
    )
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    _settle(attempt, usage.get("input_tokens"), usage.get("output_tokens"))
    try:
        text = "\n".join(
            part["text"]
            for item in data.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    except KeyError, TypeError, AttributeError:
        raise ProviderError("Provider answer format was invalid; usage recorded.") from None
    if data.get("status") != "completed":
        raise ProviderError("Provider did not complete the bounded response; usage recorded.")
    return text, usage


def _gemini(system: str, parts: list, model: str, attempt: str) -> tuple[str, dict]:
    data = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "maxOutputTokens": MAX_OUTPUT,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        },
        attempt,
    )
    usage = data.get("usageMetadata")
    usage = usage if isinstance(usage, dict) else {}
    incoming, total = usage.get("promptTokenCount"), usage.get("totalTokenCount")
    outgoing = total - incoming if type(total) is int and type(incoming) is int else None
    _settle(attempt, incoming, outgoing)
    try:
        candidate = data.get("candidates", [])[0]
        if candidate.get("finishReason") != "STOP":
            raise ProviderError("Provider did not complete the bounded response; usage recorded.")
        text = "\n".join(
            p["text"]
            for p in candidate.get("content", {}).get("parts", [])
            if "text" in p and not p.get("thought")
        )
    except IndexError, KeyError, TypeError, AttributeError:
        raise ProviderError("Provider answer format was invalid; usage recorded.") from None
    return text, {"input_tokens": incoming, "output_tokens": outgoing}


def answer(
    system: str,
    prompt: str,
    model: str,
    images: tuple[tuple[str, bytes], ...] = (),
    pdfs: tuple[tuple[str, bytes], ...] = (),
) -> tuple[str, dict]:
    """Generate one answer using an explicitly selected, configured provider.

    Args:
        system: Application-owned evidence and behavior instructions.
        prompt: Bounded machine context, question, history and evidence text.
        model: A model ID returned by available_models.
        images: Optional citation IDs and bounded PNG page views.
        pdfs: Optional citation IDs and native PDF excerpts with mappings in prompt.

    Returns:
        Answer text and normalized usage with attempt ID and measured latency.

    Raises:
        ValueError: Model unavailable or input exceeds the text budget.
        ProviderError: Provider failure, incomplete response, or empty output.
        budget.BudgetExceeded: No remaining authorized spending capacity.
    """
    if model not in MODELS or not os.environ.get(MODELS[model][1]):
        raise ValueError("Selected model is not configured.")
    size = len(system.encode()) + len(prompt.encode())
    if size > 100_000:
        raise ValueError("This context exceeds the bounded request size.")
    parts = provider_images.content(prompt, images, model)
    pdf_parts, pdf_bound = provider_pdfs.content(pdfs, model)
    parts.extend(pdf_parts)
    token_bound = size + len(images) * provider_images.IMAGE_TOKEN_BOUND + pdf_bound
    attempt = budget.reserve(model, token_bound, MAX_OUTPUT, "investigation_answer")
    started = time.monotonic()
    call = _gemini if model.startswith("gemini-") else _openai
    text, usage = call(system, parts, model, attempt)
    if not text.strip():
        raise ProviderError("Provider returned no answer text; usage recorded.")
    return text, {**usage, "attempt_id": attempt, "seconds": round(time.monotonic() - started, 3)}


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a bounded batch for the local index, accounting the actual API call.

    Args:
        texts: At most 64 nonempty snippets, each at most 6000 UTF-8 bytes.

    Returns:
        Vectors in the same order as the supplied snippets.

    Raises:
        ValueError: Invalid batch or missing OpenAI credential.
        ProviderError: Failed request, missing usage, or incomplete vector batch.
        budget.BudgetExceeded: The shared spending cap would be exceeded.
    """
    if not texts or len(texts) > 64 or any(not t or len(t.encode()) > 6000 for t in texts):
        raise ValueError("Embedding batch must contain 1–64 bounded nonempty snippets.")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OpenAI embedding credential is not configured.")
    model = "text-embedding-3-small"
    attempt = budget.reserve(model, sum(len(t.encode()) for t in texts), 0, "text_embedding")
    data = _post(
        "https://api.openai.com/v1/embeddings",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        {"model": model, "input": texts, "encoding_format": "float"},
        attempt,
    )
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    _settle(attempt, usage.get("total_tokens"), 0)
    try:
        rows = sorted(data.get("data", []), key=lambda item: item["index"])
        if [row["index"] for row in rows] != list(range(len(texts))):
            raise ProviderError("Provider returned an incomplete embedding batch; usage recorded.")
        vectors = [row["embedding"] for row in rows]
        if any(not isinstance(vector, list) or not vector for vector in vectors):
            raise ProviderError("Provider returned invalid embedding vectors; usage recorded.")
        return vectors
    except KeyError, TypeError, AttributeError:
        raise ProviderError("Provider embedding format was invalid; usage recorded.") from None
