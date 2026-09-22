"""Keep tests local: no telemetry, no OTLP export, no inherited MLflow env."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith("OTEL_") or key in {"MLFLOW_TRACKING_URI", "MLFLOW_EXPERIMENT_ID", "MLFLOW_EXPERIMENT_NAME"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
