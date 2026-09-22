"""Validate specific source support before admitting an inferred channel unit."""

import re

from pydantic import Field

from ._schemas import Input
from ._storage import read_original
from .documents import extract_document
from .onboarding_models import IntakeItem


class UnitSupport(Input):
    """Exact object-specific document passage supplied as unit evidence."""

    item_id: str
    page: int = Field(ge=1, le=250)
    quote: str = Field(min_length=1, max_length=1500)


def validate_units(db, run, preparation) -> None:
    """Reject ungrounded units; the agent can preserve values with unit unknown.

    Evidence identifies a source assertion, not independent calibration. A general
    manual's use of Celsius does not establish an unidentified sensor's unit.

    Args:
        db: Current authorized SQL session.
        run: Onboarding run defining source and installation scope.
        preparation: Validated preparation decision with its channel definitions.

    Raises:
        ValueError: A proposed unit lacks exact, object-specific source support.
    """
    for channel in preparation.channels:
        if channel.unit == "unknown":
            continue
        if any(marker in channel.column for marker in (f"[{channel.unit}]", f"({channel.unit})")):
            continue
        support = channel.unit_support
        if not support:
            raise ValueError(
                f"{channel.column}: provide source evidence in unit_support "
                "or retain unit='unknown'"
            )
        item = db.get(IntakeItem, support.item_id)
        if item is None or item.run_id != run.id or item.kind != "document":
            raise ValueError("Unit evidence must be a document from this run")
        reference = re.sub(r"^(obj|object)[_-]?", "", preparation.object_ref or "", flags=re.I)
        if not reference or not re.search(rf"(?<!\d){re.escape(reference)}(?!\d)", item.filename):
            raise ValueError("General documents cannot establish this object's sensor units")
        _, _, pages = extract_document(read_original(item), item.media_type)
        text = " ".join(pages[support.page - 1].split()) if support.page <= len(pages) else ""
        quote = " ".join(support.quote.split())
        if quote not in text or channel.unit.replace(" ", "") not in quote.replace(" ", ""):
            raise ValueError(
                "Unit citation must quote the exact page and its unit; otherwise use unknown"
            )
