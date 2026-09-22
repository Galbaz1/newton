"""Admission controls retain ambiguous charges and serialize concurrent callers."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from newton import budget
from newton.config import settings


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"ceiling": 1, "paid_attempts": []}))
    monkeypatch.setattr(settings, "budget_path", path)
    return path


def test_unknown_charge_keeps_reserve_and_blocks_overspend(ledger):
    attempt = budget.reserve("gpt-6-astra", 1000, 10000, "test")
    budget.fail(attempt, "timeout")
    state = budget.summary()
    assert state["reserved_eur"] > 0.6
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve("gpt-6-astra", 1000, 10000, "test")


def test_success_accounts_usage_and_releases_reserve(ledger):
    attempt = budget.reserve("gpt-6-astra", 1000, 1000, "test")
    budget.settle(attempt, 250, 50)
    state = budget.summary()
    assert state["reserved_eur"] == 0
    assert 0 < state["spent_eur"] < 0.02
    with pytest.raises(ValueError, match="already"):
        budget.settle(attempt, 250, 50)


def test_concurrent_calls_cannot_reserve_past_ceiling(ledger):
    def admit(_):
        try:
            return budget.reserve("gpt-6-astra", 1000, 2000, "test")
        except budget.BudgetExceeded:
            return None

    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(admit, range(20)))
    state = budget.summary()
    assert 0 < len([x for x in ids if x]) < 20
    assert state["reserved_eur"] <= 1
    assert len(json.loads(ledger.read_text())["paid_attempts"]) == len([x for x in ids if x])


def test_missing_ledger_never_creates_spending_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "budget_path", tmp_path / "missing.json")
    with pytest.raises(budget.BudgetExceeded, match="ledger"):
        budget.reserve("gpt-6-astra", 100, 100, "test")


def test_reported_overage_is_recorded_and_halts_new_calls(ledger):
    attempt = budget.reserve("gpt-6-astra", 100, 100, "test")
    with pytest.raises(ValueError, match="actual usage recorded"):
        budget.settle(attempt, 100_000, 100_000)
    state = json.loads(ledger.read_text())
    assert state["paid_attempts"][0]["status"] == "over_bound"
    assert budget.summary()["spent_eur"] > 1
    with pytest.raises(budget.BudgetExceeded, match="halted"):
        budget.reserve("text-embedding-3-small", 1, 0, "test")
