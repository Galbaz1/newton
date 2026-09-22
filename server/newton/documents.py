"""Bounded text extraction and PNG previews, with no OCR or active content execution.

PDFium is serialized within this process because its native API is not thread-safe.
Forms/JavaScript are never initialized. Parser errors expose only fixed public messages.
"""

import io
import math
import threading
import warnings

import pypdfium2 as pdfium
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

MAX_PAGES = 250
MAX_TEXT = 2_000_000
MAX_PIXELS = 16_000_000
_TEXT_PAGE_SIZE = 20_000
_PDF_LOCK = threading.Lock()
_IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def _text(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Text documents must use UTF-8 encoding") from None
    if "\x00" in text:
        raise ValueError("Text documents cannot contain binary NUL bytes")
    if len(text) > MAX_TEXT:
        raise ValueError("Document exceeds the 2 million character extraction limit")
    pages = []
    for section in text.split("\f"):
        pages.extend(
            section[start : start + _TEXT_PAGE_SIZE]
            for start in range(0, len(section), _TEXT_PAGE_SIZE)
        )
        if not section:
            pages.append("")
    if len(pages) > MAX_PAGES:
        raise ValueError("Document exceeds the 250 page limit")
    return pages


def _pdf_text(data: bytes) -> list[str]:
    with _PDF_LOCK, pdfium.PdfDocument(data) as document:
        if not 0 < len(document) <= MAX_PAGES:
            raise ValueError("PDF must contain between 1 and 250 pages")
        result, total = [], 0
        for number in range(len(document)):
            page = document[number]
            try:
                text_page = page.get_textpage()
                total += text_page.count_chars()
                if total > MAX_TEXT:
                    raise ValueError("PDF exceeds the 2 million character extraction limit")
                result.append(text_page.get_text_range())
            finally:
                page.close()
        return result


def _open_image(data: bytes, media_type: str):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(data))
    try:
        if image.format != _IMAGE_FORMATS[media_type]:
            raise ValueError("Image contents do not match its file type")
        if image.width * image.height > MAX_PIXELS:
            raise ValueError("Image exceeds the 16 million pixel limit")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Animated images are not supported; upload a single frame")
        image.load()
        return image
    except Exception:
        image.close()
        raise


def extract_document(data: bytes, media_type: str) -> tuple[str, dict, list[str]]:
    """Extract bounded pages and explicit readiness; keep corrupt originals as errors.

    Args:
        data: Exact uploaded bytes, already bounded by the intake boundary.
        media_type: Validated supported document or image media type.

    Returns:
        Status, public metadata, and one-based page texts (including blank image pages).
    """
    try:
        if media_type in _IMAGE_FORMATS:
            with _open_image(data, media_type) as image:
                metadata = {
                    "page_count": 1,
                    "width": image.width,
                    "height": image.height,
                    "warnings": ["No text extracted from image; inspect the original visually"],
                }
            return "needs_text", metadata, [""]
        pages = _pdf_text(data) if media_type == "application/pdf" else _text(data)
        blank = sum(not page.strip() for page in pages)
        metadata = {"page_count": len(pages)}
        if any("placeholder samenvatting voor testdoeleinden" in p.lower() for p in pages):
            metadata["evidence_caveats"] = [
                "This supplied report contains an explicit test placeholder. Its generated "
                "health scores, conclusions and plotted period are not original observations. "
                "Asset descriptions are attributed source assertions; verify time periods."
            ]
        if blank:
            metadata["warnings"] = [
                f"{blank} page(s) have no embedded text; interpret the original PDF visually"
            ]
        return "ready" if any(page.strip() for page in pages) else "needs_text", metadata, pages
    except ValueError as error:
        return "error", {"page_count": 0, "error": str(error)}, []
    except (
        pdfium.PdfiumError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return (
            "error",
            {"page_count": 0, "error": "File cannot be safely decoded or is encrypted"},
            [],
        )


def _pdf_png(data: bytes, number: int) -> bytes:
    with _PDF_LOCK, pdfium.PdfDocument(data) as document:
        if not 1 <= number <= len(document):
            raise HTTPException(404, "Page not found")
        page = document[number - 1]
        width, height = page.get_size()
        if not all(math.isfinite(size) and 0 < size <= 100_000 for size in (width, height)):
            raise ValueError("Invalid PDF page dimensions")
        scale = min(1.5, 4000 / max(width, height))
        bitmap = page.render(scale=scale, may_draw_forms=False)
        try:
            with bitmap.to_pil() as image:
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
        finally:
            bitmap.close()


def pdf_excerpt(data: bytes, pages: list[int]) -> bytes:
    """Copy up to three original PDF pages without rasterizing or transcribing them.

    Args:
        data: Integrity-checked original PDF bytes.
        pages: Unique one-based original page numbers in the intended order.

    Returns:
        A derived PDF retaining the selected pages' text and graphical content.
        The caller must retain the original hash and this explicit page mapping.

    Raises:
        ValueError: The selection is empty, duplicated, oversized or out of range.
    """
    if not 1 <= len(pages) <= 3 or len(set(pages)) != len(pages):
        raise ValueError("Select one to three distinct original PDF pages")
    with _PDF_LOCK, pdfium.PdfDocument(data) as source, pdfium.PdfDocument.new() as result:
        if any(type(page) is not int or not 1 <= page <= len(source) for page in pages):
            raise ValueError("Requested page is outside the original document")
        result.import_pages(source, pages=[page - 1 for page in pages])
        output = io.BytesIO()
        result.save(output)
        return output.getvalue()


def render_page(data: bytes, media_type: str, number: int) -> bytes:
    """Return an inert PNG preview or fixed 404/422 errors; never serve active HTML."""
    if number < 1:
        raise HTTPException(404, "Page not found")
    try:
        if media_type == "application/pdf":
            return _pdf_png(data, number)
        if media_type in _IMAGE_FORMATS and number == 1:
            with _open_image(data, media_type) as image:
                output = io.BytesIO()
                image.thumbnail((4000, 4000))
                image.convert("RGB").save(output, format="PNG")
                return output.getvalue()
    except (
        ValueError,
        pdfium.PdfiumError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(422, "Page cannot be safely rendered") from None
    raise HTTPException(404, "No image is available for this page")
