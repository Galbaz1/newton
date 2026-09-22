"""Atomic, conservative admission for the explicitly authorized API spending cap.

Rates are dated estimates, not invoices. UTF-8 byte counts bound text tokens;
ambiguous failures keep their full reserve until a human reconciles usage.
"""

import fcntl
import json
import math
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from newton.config import settings

# USD per million tokens, including a conservative cache-write allowance.
# Gemini rates are introductory through 2026-12-31. Refresh before later calls.
RATES = {
    "gpt-6-astra": (12.5, 50.0),
    "gpt-5.6-sol": (5.0, 20.0),
    "gemini-3.8-flash": (0.75, 3.75),
    "text-embedding-3-small": (0.02, 0.0),
}
EUR_MARGIN = 1.25


class BudgetExceeded(ValueError):
    """A call has no verified room under the configured spending ceiling."""


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    incoming, outgoing = RATES[model]
    usd = (input_tokens * incoming + output_tokens * outgoing) / 1_000_000
    return math.ceil(usd * EUR_MARGIN * 1_000_000) / 1_000_000


def _totals(state: dict) -> tuple[float, float]:
    spent = sum(row.get("accounted_eur", 0) for row in state["paid_attempts"])
    reserved = sum(
        row["reserve_eur"]
        for row in state["paid_attempts"]
        if row["status"] in {"reserved", "unknown"}
    )
    return round(spent, 6), round(reserved, 6)


@contextmanager
def _locked():
    path = settings.budget_path
    if not path.exists():
        raise BudgetExceeded("No budget ledger exists; paid calls are disabled.")
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text())
        yield state
        state["accounted_eur"], state["reserved_eur"] = _totals(state)
        temporary = path.with_suffix(".pending")
        with temporary.open("w") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)


def reserve(
    model: str,
    input_token_bound: int,
    max_output: int,
    purpose: str,
    tool_fee_bound: float = 0,
) -> str:
    """Reserve a worst-case charge before making a provider request.

    Args:
        model: An explicitly priced model identifier.
        input_token_bound: Conservative text-token bound (UTF-8 bytes) plus bounded image tokens.
        max_output: Enforced provider output-token ceiling, including reasoning.
        purpose: Short non-sensitive operation label, never source text.
        tool_fee_bound: Additional conservative EUR reserve for metered provider tools.

    Returns:
        A durable attempt ID to settle or mark unknown after the request.

    Raises:
        BudgetExceeded: Ledger missing, rates expired, or insufficient budget.
        ValueError: An unpriced model or invalid request bounds were supplied.
    """
    if model not in RATES or input_token_bound < 0 or max_output < 0 or tool_fee_bound < 0:
        raise ValueError("Unknown model or invalid usage bounds.")
    if datetime.now(UTC).date().isoformat() > "2026-12-31":
        raise BudgetExceeded("Refresh dated provider rates before paid calls.")
    reserve_eur = round(_cost(model, input_token_bound + 1024, max_output) + tool_fee_bound, 6)
    with _locked() as state:
        if state.get("halt_reason"):
            raise BudgetExceeded(
                "Budget admission is halted; reconcile the recorded usage anomaly."
            )
        spent, pending = _totals(state)
        if spent + pending + reserve_eur > state["ceiling"]:
            raise BudgetExceeded("This request exceeds the remaining API budget.")
        attempt = str(uuid4())
        state["paid_attempts"].append(
            {
                "id": attempt,
                "model": model,
                "purpose": purpose,
                "status": "reserved",
                "created_at": datetime.now(UTC).isoformat(),
                "reserve_eur": reserve_eur,
                "input_token_bound": input_token_bound + 1024,
                "output_token_bound": max_output,
                "tool_fee_bound_eur": tool_fee_bound,
            }
        )
    return attempt


def settle(
    attempt_id: str,
    input_tokens: int,
    output_tokens: int,
    tool_fee_eur: float = 0,
) -> None:
    """Account reported usage and release this attempt's conservative reserve.

    Args:
        attempt_id: ID returned by reserve.
        input_tokens: Provider-reported input usage; cached input is overcounted.
        output_tokens: All billed output, including reasoning/thinking tokens.
        tool_fee_eur: Conservatively accounted metered tools; free allowance is ignored.

    Raises:
        ValueError: Attempt already settled or provider usage violates the bound.
    """
    over_bound = False
    with _locked() as state:
        row = next(item for item in state["paid_attempts"] if item["id"] == attempt_id)
        if row["status"] not in {"reserved", "unknown"}:
            raise ValueError("Attempt already settled.")
        charge = round(_cost(row["model"], input_tokens, output_tokens) + tool_fee_eur, 6)
        if min(input_tokens, output_tokens, tool_fee_eur) < 0:
            raise ValueError("Reported usage cannot be negative.")
        over_bound = charge > row["reserve_eur"]
        row.update(
            status="complete",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_fee_eur=tool_fee_eur,
            accounted_eur=charge,
            completed_at=datetime.now(UTC).isoformat(),
        )
        if over_bound:
            row["status"] = "over_bound"
            state["halt_reason"] = "Provider-reported usage exceeded its admitted bound."
    if over_bound:
        raise ValueError("Reported usage exceeds its admitted bound; actual usage recorded.")


def fail(attempt_id: str, category: str) -> None:
    """Retain full reservation when a failed request has no trustworthy usage.

    Args:
        attempt_id: ID returned by reserve.
        category: Non-sensitive error class or HTTP status; never a response body.
    """
    with _locked() as state:
        row = next(item for item in state["paid_attempts"] if item["id"] == attempt_id)
        if row["status"] == "reserved":
            row.update(status="unknown", error=category, failed_at=datetime.now(UTC).isoformat())


def summary() -> dict:
    """Return the public budget totals without exposing individual request records."""
    with _locked() as state:
        spent, reserved = _totals(state)
        return {"ceiling_eur": state["ceiling"], "spent_eur": spent, "reserved_eur": reserved}
