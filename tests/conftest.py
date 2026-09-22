"""Keep optional remote inference disconnected from the default offline suite."""

import pytest
from newton.config import settings


@pytest.fixture(autouse=True)
def no_remote_encoder(monkeypatch):
    """Tests explicitly opt into a mocked encoder; local operator config cannot leak in."""
    monkeypatch.setattr(settings, "visual_encoder_url", "")
