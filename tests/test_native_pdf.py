"""Native PDFs retain page content, source scope and conservative paid-call admission."""

import base64
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from newton import answer_documents, documents, intake_execution, intake_visual, providers
from newton._storage import read_original
from newton.config import settings
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_onboarding_safety import _entry, _finish, _item
from test_onboarding_safety import offline as offline
from test_onboarding_safety import world as world


def synthetic_pdf():
    writer = PdfWriter()
    for text in ("SOURCE FIRST", "SOURCE SECOND", "SOURCE THIRD", "SOURCE FOURTH"):
        page = writer.add_blank_page(width=320, height=240)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET 1 0 0 rg 20 20 50 40 re f".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def pdf_item(world):
    item = _item(world, data=synthetic_pdf(), filename="original.pdf", kind="document")
    item.media_type = "application/pdf"
    world.db.commit()
    return item


def test_copy_preserves_text_and_rendered_graphics_in_selected_order():
    data = synthetic_pdf()
    original_hash = hashlib.sha256(data).hexdigest()
    copied = documents.pdf_excerpt(data, [3, 1])
    assert documents.extract_document(copied, "application/pdf")[2] == [
        "SOURCE THIRD",
        "SOURCE FIRST",
    ]
    for output_page, original_page in enumerate([3, 1], 1):
        assert documents.render_page(copied, "application/pdf", output_page) == (
            documents.render_page(data, "application/pdf", original_page)
        )
    assert hashlib.sha256(data).hexdigest() == original_hash


@pytest.mark.parametrize("pages", [[], [0], [5], [1, 1], [1, 2, 3, 4]])
def test_invalid_pdf_selection_rejected(pages):
    with pytest.raises(ValueError):
        documents.pdf_excerpt(synthetic_pdf(), pages)


def test_inspection_sends_native_pdf_and_reuses_exact_paid_receipt(world, monkeypatch):
    item = pdf_item(world)
    call = Mock(
        return_value=("Afgeleid: rode rechthoek, geen installatienummer.", {"attempt_id": "x"})
    )
    monkeypatch.setattr(providers, "answer", call)
    args = intake_visual.Inspection(item_id=item.id, pages=[2], question="Wat is zichtbaar?")
    result = intake_visual.inspect(world.db, world.runs[0], args)
    assert call.call_args.args[3] == ()
    assert call.call_args.args[4][0][1].startswith(b"%PDF-")
    assert result["model_input"]["original_pages"] == [2]
    assert result["original_sha256"] == item.sha256
    assert result["evidence_class"] == "generated_observation"
    assert intake_visual.inspect(world.db, world.runs[0], args) == result
    assert call.call_count == 1
    assert documents.extract_document(read_original(item), item.media_type)[2][0] == "SOURCE FIRST"
    assert item.profile["visual_observation"] == result


def test_inspection_denies_foreign_item_before_paid_call(world):
    item = _item(world, run=world.runs[1])
    with pytest.raises(ValueError, match="does not belong"):
        intake_visual.inspect(
            world.db,
            world.runs[0],
            intake_visual.Inspection(item_id=item.id, pages=[1], question="Inspect"),
        )


def test_photo_preparation_requires_actual_inspection(world, monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(output, format="PNG")
    item = _item(world, data=output.getvalue(), filename="photo.png", kind="image")
    item.media_type = "image/png"
    world.db.commit()
    args = intake_execution.Preparations(sources=[_entry(item, disposition="quarantine")])
    with pytest.raises(ValueError, match="Inspect the image"):
        intake_execution.prepare(world.db, world.runs[0], args)
    call = Mock(return_value=("Rood vlak. Identiteit onbekend.", {"attempt_id": "x"}))
    monkeypatch.setattr(providers, "answer", call)
    intake_visual.inspect(
        world.db,
        world.runs[0],
        intake_visual.Inspection(item_id=item.id, pages=[1], question="Inspect identity"),
    )
    assert call.call_args.args[3][0][1].startswith(b"\x89PNG")
    assert call.call_args.args[4] == ()
    assert (
        intake_execution.prepare(world.db, world.runs[0], args)["results"][0]["status"]
        == "quarantined"
    )
    assert read_original(item) == output.getvalue()


def test_resumed_image_decision_requires_current_visual_observation(world, monkeypatch):
    from newton import onboarding_questions
    from newton.models import Source

    output = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(output, format="PNG")
    item = _item(world, data=output.getvalue(), filename="photo.png", kind="image")
    item.media_type = "image/png"
    item.profile = {"visual_observation": {"observation": "Earlier interpretation"}}
    world.db.commit()
    args = intake_execution.Preparations(sources=[_entry(item, disposition="quarantine")])
    intake_execution.prepare(world.db, world.runs[0], args)
    source = world.db.get(Source, item.source_id)
    original_hash, old_version = source.sha256, source.version
    item.profile = {}
    world.db.commit()
    with pytest.raises(ValueError, match="Inspect every image"):
        onboarding_questions.finish(world.db, world.runs[0], _finish([source.id]))
    monkeypatch.setattr(providers, "answer", Mock(return_value=("Identity unresolved", {})))
    observation = intake_visual.inspect(
        world.db,
        world.runs[0],
        intake_visual.Inspection(item_id=item.id, pages=[1], question="Inspect identity"),
    )
    intake_execution.prepare(world.db, world.runs[0], args)
    assert source.metadata_json["profile"]["visual_observation"] == observation
    assert source.version == old_version + 1
    assert source.sha256 == original_hash
    assert onboarding_questions.finish(world.db, world.runs[0], _finish([source.id]))["finished"]


def test_public_onboarding_summary_uses_actual_counts_not_model_prose(world):
    from newton.onboarding_state import run_json

    item = _item(world)
    item.status = "quarantined"
    run = world.runs[0]
    run.summary = "All 99 images visually verified; onboarding complete."
    run.state = {**run.state, "agent_finished": True}
    world.db.commit()
    result = run_json(world.db, run)
    assert "99" not in result["summary"]
    assert "Behouden bestanden: 1" in result["summary"]
    assert "1 apart gehouden" in result["summary"]
    assert "Visueel bekeken afbeeldingen: 0 van 0" in result["summary"]
    assert result["status"] == "running"


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "gpt-5.6-sol"])
def test_native_pdf_wire_and_token_admission(world, monkeypatch, model):
    from newton import budget, provider_pdfs

    data = documents.pdf_excerpt(synthetic_pdf(), [1])
    reserve = Mock(return_value="synthetic-attempt")
    monkeypatch.setattr(budget, "reserve", reserve)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(providers, "answer", providers_answer)
    call = Mock(return_value=("Verified wire", {}))
    monkeypatch.setattr(providers, "_gemini" if model.startswith("gemini") else "_openai", call)
    providers.answer("system", "source pages: [1]", model, (), (("E1", data),))
    parts = call.call_args.args[1]
    encoded = (
        parts[2].get("inlineData", {}).get("data")
        if model.startswith("gemini")
        else (parts[2]["file_data"].split(",", 1)[1])
    )
    assert base64.b64decode(encoded) == data
    assert reserve.call_args.args[1] >= provider_pdfs.IMAGE_TOKEN_BOUND + len("SOURCE FIRST")
    with pytest.raises(ValueError, match="12 MiB"):
        provider_pdfs.content((("E1", b"x" * (12 * 1024 * 1024 + 1)),), model)


providers_answer = providers.answer


def test_answer_pdf_scope_mapping_and_retained_input(world, monkeypatch):
    item = pdf_item(world)
    source = SimpleNamespace(
        company_id="c",
        machine_id="m",
        data_class="original",
        status="ready",
        version=2,
        media_type="application/pdf",
        metadata_json={"page_count": 4},
        storage_path=item.storage_path,
        sha256=item.sha256,
    )
    db = SimpleNamespace(get=lambda *args, **kw: source)
    machine = SimpleNamespace(id="m", company_id="c")
    record = {"id": "E1", "source_id": "s", "source_version": 2, "page": 2}
    images, pdfs, warnings = answer_documents.attach_pdfs(
        db, machine, [record], [("E1", b"unused")]
    )
    assert warnings == []
    assert images == [] and len(pdfs) == 1
    assert record["model_input"]["original_pages"] == [1, 2, 3]
    assert documents.extract_document(pdfs[0][1], "application/pdf")[2] == [
        "SOURCE FIRST",
        "SOURCE SECOND",
        "SOURCE THIRD",
    ]
    saved = settings.data_dir / "answer-pdfs" / f"{record['model_input']['sha256']}.pdf"
    assert saved.read_bytes() == pdfs[0][1]
    for field, value in [("company_id", "foreign"), ("version", 3), ("status", "quarantined")]:
        previous = getattr(source, field)
        setattr(source, field, value)
        with pytest.raises(ValueError, match="Source context changed"):
            answer_documents.attach_pdfs(db, machine, [record], [])
        setattr(source, field, previous)
