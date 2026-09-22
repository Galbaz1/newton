"""Answer selection stays within native PDF limits without pretending omitted pages were seen."""

from types import SimpleNamespace

from newton import answer_documents, documents, provider_pdfs
from test_native_pdf import synthetic_pdf
from test_onboarding_safety import offline as offline
from test_onboarding_safety import world as world


def selection(world, monkeypatch, pages):
    original = synthetic_pdf()
    source = SimpleNamespace(
        company_id="company",
        machine_id="machine",
        data_class="original",
        status="ready",
        version=1,
        media_type="application/pdf",
        metadata_json={"page_count": 4},
        sha256="original-hash",
        filename="manual.pdf",
    )
    monkeypatch.setattr(answer_documents, "read_original", lambda _: original)
    db = SimpleNamespace(get=lambda *args, **kwargs: source)
    machine = SimpleNamespace(id="machine", company_id="company")
    records = [
        {"id": f"E{i}", "source_id": "source", "source_version": 1, "page": page}
        for i, page in enumerate(pages, 1)
    ]
    return db, machine, records


def test_duplicate_source_pages_share_one_native_pdf(world, monkeypatch):
    db, machine, records = selection(world, monkeypatch, [2, 2])
    result = answer_documents.attach_pdfs(db, machine, records, [])
    pdfs = result[1]
    assert len(pdfs) == 1
    assert "E1" in pdfs[0][0] and "E2" in pdfs[0][0]
    assert records[0]["model_input"] == records[1]["model_input"]
    assert records[0]["model_input"]["original_pages"] == [1, 2, 3]


def test_byte_limit_reduces_context_then_explicitly_excludes_unseen_candidate(world, monkeypatch):
    db, machine, records = selection(world, monkeypatch, [2, 4])
    limit = len(documents.pdf_excerpt(synthetic_pdf(), [2])) + 1
    monkeypatch.setattr(provider_pdfs, "MAX_PDF_BYTES", limit, raising=False)
    result = answer_documents.attach_pdfs(
        db, machine, records, [("E1", b"view1"), ("E2", b"view2")]
    )
    assert sum(len(data) for _, data in result[1]) <= limit
    assert len(records) == 1 and records[0]["id"] == "E1"
    assert records[0]["model_input"]["original_pages"] == [2]
    assert result[0] == []  # No silent fallback to a PNG or extracted text for omitted PDFs.
    assert any("adjacent" in warning for warning in result[2])
    assert any("E2" in warning and "not supplied" in warning for warning in result[2])


def test_excerpt_count_does_not_abort_other_evidence(world, monkeypatch):
    db, machine, records = selection(world, monkeypatch, [1, 4])
    monkeypatch.setattr(provider_pdfs, "MAX_PDF_EXCERPTS", 1, raising=False)
    result = answer_documents.attach_pdfs(db, machine, records, [])
    assert len(result[1]) == 1 and len(records) == 1
    assert any("E2" in warning and "not supplied" in warning for warning in result[2])
