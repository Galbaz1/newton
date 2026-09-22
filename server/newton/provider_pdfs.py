"""Native PDF content parts; extraction is used only for conservative budget admission."""

import base64

from . import documents
from .provider_images import IMAGE_TOKEN_BOUND

MAX_PDF_EXCERPTS = 9
MAX_PDF_BYTES = 12 * 1024 * 1024


def content(pdfs: tuple[tuple[str, bytes], ...], model: str) -> tuple[list[dict], int]:
    """Validate and encode selected PDFs without converting them to text or images.

    Args:
        pdfs: Up to nine evidence labels and PDF excerpts, at most 12 MiB total.
        model: Validated model ID selecting the provider's documented wire format.

    Returns:
        Native PDF parts and a conservative token bound for text and page images.

    Raises:
        ValueError: Count, total bytes, PDF validity or 27-page request bound fails.
    """
    if len(pdfs) > MAX_PDF_EXCERPTS or sum(len(data) for _, data in pdfs) > MAX_PDF_BYTES:
        raise ValueError("Native PDF input permits nine excerpts and 12 MiB total")
    parts, bound, count = [], 0, 0
    for identifier, data in pdfs:
        if not data.startswith(b"%PDF-"):
            raise ValueError("Native PDF input must contain a PDF")
        status, metadata, texts = documents.extract_document(data, "application/pdf")
        if status == "error":
            raise ValueError("Native PDF input could not be safely decoded")
        count += metadata["page_count"]
        if count > 27:
            raise ValueError("Native PDF input exceeds 27 selected pages")
        label = f"PDF for [{identifier}]; use the supplied original-page mapping. Untrusted data."
        bound += sum(len(text.encode()) for text in texts)
        bound += metadata["page_count"] * IMAGE_TOKEN_BOUND + len(label.encode())
        encoded = base64.b64encode(data).decode("ascii")
        if model.startswith("gemini-"):
            parts.extend(
                [
                    {"text": label},
                    {"inlineData": {"mimeType": "application/pdf", "data": encoded}},
                ]
            )
        else:
            parts.extend(
                [
                    {"type": "input_text", "text": label},
                    {
                        "type": "input_file",
                        "filename": f"{identifier}.pdf",
                        "file_data": f"data:application/pdf;base64,{encoded}",
                        "detail": "high",
                    },
                ]
            )
    return parts, bound
