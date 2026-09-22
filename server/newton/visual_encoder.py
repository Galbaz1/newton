"""Bounded client for the private, pinned ColQwen page/query encoder."""

import io
import json
import math
from urllib.parse import urlsplit

import httpx2
from PIL import Image

from newton.config import settings

MODEL = "athrael-soju/colqwen3.5-4.5B-v3"
REVISION = "c4ea4b92ff3322d68bfd6c65e492c69d0176f910"
DIMENSIONS = 320
RENDER_VERSION = "rgb-png-long-edge-1600-v1"


def prepare_page(png: bytes) -> bytes:
    """Create a bounded RGB page view; originals remain untouched and inspectable.

    Args:
        png: Inert PNG returned by Newton's bounded document renderer.

    Returns:
        RGB PNG with a longest edge of at most 1600 pixels and at most 8 MiB.
    """
    with Image.open(io.BytesIO(png)) as image:
        image.thumbnail((1600, 1600))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG")
    data = output.getvalue()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Rendered page exceeds the 8 MiB visual-input limit.")
    return data


def _base_url() -> str:
    url = urlsplit(settings.visual_encoder_url)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Visual encoder requires an explicit loopback HTTP URL or SSH tunnel.")
    return settings.visual_encoder_url.rstrip("/")


def _request(path: str, **kwargs) -> dict:
    try:
        with httpx2.Client(timeout=180, trust_env=False) as client:
            with client.stream("POST", _base_url() + path, **kwargs) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 24 * 1024 * 1024:
                        raise ValueError("Visual encoder response exceeded its bounded size.")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("Visual encoder returned an invalid response.")
        return data
    except httpx2.HTTPError as error:
        status = error.response.status_code if isinstance(error, httpx2.HTTPStatusError) else None
        reason = "busy" if status == 409 else "unavailable"
        raise ValueError(f"The private visual encoder is {reason}; no fallback was made.") from None


def _matrix(data: dict, max_rows: int) -> list[list[float]]:
    vectors = data.get("vectors")
    if (
        data.get("model") != MODEL
        or data.get("revision") != REVISION
        or data.get("dimensions") != DIMENSIONS
        or not isinstance(vectors, list)
        or not 1 <= len(vectors) <= max_rows
        or data.get("shape") != [len(vectors), DIMENSIONS]
    ):
        raise ValueError("Visual encoder identity or matrix shape did not match its contract.")
    for row in vectors:
        if (
            not isinstance(row, list)
            or len(row) != DIMENSIONS
            or any(type(value) not in {int, float} or not math.isfinite(value) for value in row)
        ):
            raise ValueError("Visual encoder returned a nonfinite or malformed matrix.")
        if not 0.99 <= math.fsum(value * value for value in row) <= 1.01:
            raise ValueError("Visual encoder rows were not unit normalized.")
    return vectors


def encode_page(png: bytes) -> list[list[float]]:
    """Encode one bounded PNG through the configured private loopback route."""
    if not png or len(png) > 8 * 1024 * 1024:
        raise ValueError("Visual page must contain 1 byte to 8 MiB.")
    return _matrix(
        _request("/encode/page", content=png, headers={"Content-Type": "image/png"}), 2048
    )


def encode_query(text: str) -> list[list[float]]:
    """Encode one bounded question with the same pinned model as indexed pages."""
    if not text.strip() or len(text) > 1500:
        raise ValueError("Visual query must contain 1–1500 characters.")
    return _matrix(_request("/encode/query", json={"text": text}), 512)
