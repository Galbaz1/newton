"""Resolve PDF candidates to bounded, scoped original content before inference."""

import hashlib

from . import documents, provider_pdfs
from ._storage import read_original
from .config import settings
from .models import Source


def _source(db, machine, record):
    source = db.get(Source, record["source_id"], populate_existing=True)
    if (
        source is None
        or source.company_id != machine.company_id
        or source.machine_id not in {None, machine.id}
        or source.data_class not in {"original", "derived"}
        or source.status not in {"ready", "needs_text"}
        or source.version != record["source_version"]
    ):
        raise ValueError("Source context changed before native PDF interpretation")
    return source


def _excerpt(source, page, available):
    count = source.metadata_json["page_count"]
    if type(page) is not int or not 1 <= page <= count:
        raise ValueError("PDF candidate page is outside the original document")
    original = read_original(source)
    pages = list(range(max(1, page - 1), min(count, page + 1) + 1))
    data = documents.pdf_excerpt(original, pages)
    reduced = len(data) > available and len(pages) > 1
    if reduced:
        pages = [page]
        data = documents.pdf_excerpt(original, pages)
    return pages, data, reduced


def _retain(data, pages):
    metadata = {
        "format": "application/pdf",
        "original_pages": pages,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "operation": "pdfium-copy-pages-v1",
    }
    directory = settings.data_dir / "answer-pdfs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{metadata['sha256']}.pdf"
    path.write_bytes(data)
    path.chmod(0o600)
    return metadata


def attach_pdfs(db, machine, evidence: list[dict], images: list[tuple]) -> tuple:
    """Select native candidate pages in retrieval order within the request budget.

    Args:
        db: Authoritative SQL session after authenticated retrieval.
        machine: Authorized machine defining company and optional asset scope.
        evidence: Records enriched in place; unprovided PDF candidates are removed.
        images: Page views, replaced by native content for all PDF candidates.

    Returns:
        Remaining images, labeled PDF excerpts and explicit selection warnings.
        Repeated candidates share one input. Adjacent context is reduced before a
        candidate is excluded; excluded text/PNG never masquerades as an inspected PDF.

    Raises:
        ValueError: Source access/version changed or a candidate page is invalid.
    """
    selected, pdf_ids, accepted, warnings = {}, set(), [], []
    total = 0
    for record in evidence:
        source = _source(db, machine, record)
        if source.media_type != "application/pdf":
            accepted.append(record)
            continue
        pdf_ids.add(record["id"])
        key = (record["source_id"], record["page"])
        if key not in selected:
            pages, data, reduced = _excerpt(
                source, record["page"], provider_pdfs.MAX_PDF_BYTES - total
            )
            if (
                len(selected) >= provider_pdfs.MAX_PDF_EXCERPTS
                or total + len(data) > provider_pdfs.MAX_PDF_BYTES
            ):
                warnings.append(
                    f"[{record['id']}] {source.filename}, page {record['page']}: "
                    "native PDF not supplied due to input limits; excluded from answer evidence."
                )
                continue
            selected[key] = {"labels": [], "data": data, "metadata": _retain(data, pages)}
            total += len(data)
            if reduced:
                warnings.append(
                    f"[{record['id']}] {source.filename}, page {record['page']}: "
                    "adjacent pages omitted to fit the native PDF input limit."
                )
        entry = selected[key]
        entry["labels"].append(record["id"])
        record["model_input"] = entry["metadata"]
        record["original_sha256"] = source.sha256
        accepted.append(record)
    evidence[:] = accepted
    pdfs = [(", ".join(entry["labels"]), entry["data"]) for entry in selected.values()]
    return [image for image in images if image[0] not in pdf_ids], pdfs, warnings
