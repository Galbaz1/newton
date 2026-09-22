"""Synthetic source originals, previews and tenant denial through actual HTTP routes."""

import hashlib
import io
import stat

import pytest
from fastapi.testclient import TestClient
from newton import db
from newton.config import settings
from newton.models import Page, Source
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select


def _upload(client, owner, name, content, mime):
    return client.post(
        f"/api/machines/{owner['machine']['id']}/sources",
        files={"file": (name, content, mime)},
        data={"revision": "Synthetic v1"},
    )


def test_original_hash_pages_correction_and_delete(client, owner):
    """Bytes/hash survive revisions and all source mutations increment machine context."""
    content = b"SYNTHETIC page one\n<script>alert('text only')</script>\fPage two\n"
    response = _upload(client, owner, "../../original.txt", content, "text/plain")
    assert response.status_code == 200
    source = response.json()
    assert set(source) == {
        "id",
        "company_id",
        "data_class",
        "machine_id",
        "filename",
        "media_type",
        "sha256",
        "kind",
        "status",
        "revision",
        "version",
        "mapping",
        "metadata",
        "created_at",
    }
    assert source["filename"] == "original.txt"
    assert source["sha256"] == hashlib.sha256(content).hexdigest()
    assert source["status"] == "ready" and source["metadata"]["page_count"] == 2
    machine_path = f"/api/machines/{owner['machine']['id']}"
    assert client.get(machine_path).json()["context_version"] == 2
    path = f"/api/sources/{source['id']}"
    original = client.get(path + "/original")
    assert original.content == content
    assert original.headers["content-disposition"] == 'attachment; filename="original.txt"'
    assert original.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in original.headers["cache-control"]
    pages = client.get(path + "/pages").json()
    assert len(pages) == 2 and pages[0]["number"] == 1
    assert set(pages[0]) == {"id", "number", "text"}
    assert "<script>" in pages[0]["text"]
    assert client.get(path + "/pages/1/image").status_code == 404
    assert client.get(path + "/series").status_code == 404
    correction = client.patch(path, json={"revision": "Corrected label"}).json()
    assert correction["version"] == 2 and correction["sha256"] == source["sha256"]
    assert client.get(path + "/original").content == content
    assert client.get(machine_path).json()["context_version"] == 3
    with db.SessionLocal() as session:
        stored = session.get(Source, source["id"])
        file = settings.data_dir / "originals" / stored.storage_path
        assert file.read_bytes() == content
        assert stat.S_IMODE(file.stat().st_mode) == 0o400
        assert stat.S_IMODE(file.parent.stat().st_mode) == 0o700
    assert client.delete(path).json() == {"ok": True}
    assert not file.exists()
    assert client.get(path + "/original").status_code == 404
    assert client.get(machine_path).json()["context_version"] == 4
    with db.SessionLocal() as session:
        assert session.get(Source, source["id"]) is None
        assert list(session.scalars(select(Page))) == []


def test_pdf_text_blank_page_and_png_rendering(client, owner, pdf_bytes):
    """Real PDF text and blank pages are indexed without inventing OCR output."""
    source = _upload(client, owner, "synthetic.pdf", pdf_bytes, "application/pdf").json()
    assert source["status"] == "ready" and source["metadata"]["page_count"] == 2
    assert source["metadata"]["warnings"]
    path = f"/api/sources/{source['id']}"
    pages = client.get(path + "/pages").json()
    assert "SYNTHETIC maintenance instructions" in pages[0]["text"]
    assert pages[1]["text"] == ""
    for number in (1, 2):
        image = client.get(path + f"/pages/{number}/image")
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(image.content)) as preview:
            assert preview.width > 0 and preview.height > 0
    assert client.get(path + "/pages/0/image").status_code == 404
    assert client.get(path + "/pages/3/image").status_code == 404
    assert client.get(path + "/original").content == pdf_bytes


def test_scanned_pdf_and_image_need_text(client, owner, png_bytes):
    """Blank PDFs and raster images remain inspectable with honest text readiness."""
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    for name, data, mime in (
        ("scan.pdf", stream.getvalue(), "application/pdf"),
        ("synthetic.png", png_bytes, "image/png"),
    ):
        source = _upload(client, owner, name, data, mime).json()
        assert source["status"] == "needs_text"
        path = f"/api/sources/{source['id']}"
        assert client.get(path + "/pages").json()[0]["text"] == ""
        assert client.get(path + "/pages/1/image").status_code == 200
        assert client.get(path + "/original").content == data
    readiness = client.get(f"/api/machines/{owner['machine']['id']}/readiness").json()
    assert readiness["source_count"] == 2
    assert readiness["context_version"] == 3
    assert {row["id"]: row["state"] for row in readiness["capabilities"]} == {
        "document": "needs_text",
        "image": "ready",
        "timeseries": "missing",
        "visual_search": "missing",
    }


def test_foreign_source_routes_and_spoofed_company_are_denied(client, owner, app, png_bytes):
    """A second account cannot traverse sources, originals, pages, images or series."""
    image = _upload(client, owner, "synthetic.png", png_bytes, "image/png").json()
    csv = _upload(client, owner, "synthetic.csv", b"t,v\n2026-01-01T00:00Z,3\n", "text/csv").json()
    client.patch(
        f"/api/sources/{csv['id']}",
        json={
            "mapping": {"time_column": "t", "value_column": "v", "unit": "bar"},
        },
    )
    with TestClient(app) as other:
        other.post(
            "/api/auth/register",
            json={
                "email": "intruder@example.test",
                "password": "synthetic password 456",
            },
        )
        for source in (image, csv):
            path = f"/api/sources/{source['id']}"
            for suffix in ("/original", "/pages", "/pages/1/image", "/series"):
                denied = other.get(path + suffix)
                assert denied.status_code == 404
                assert set(denied.json()) == {"detail"}
                assert "storage" not in denied.text
            assert other.patch(path, json={"revision": "Intrusion"}).status_code == 404
            assert other.delete(path).status_code == 404
        machine_path = f"/api/machines/{owner['machine']['id']}"
        assert other.get(machine_path + "/sources").status_code == 404
        assert other.get(machine_path + "/readiness").status_code == 404
        assert (
            other.post(
                machine_path + "/sources",
                files={
                    "file": ("test.txt", b"Synthetic", "text/plain"),
                },
            ).status_code
            == 404
        )
    assert (
        client.patch(f"/api/sources/{image['id']}", json={"company_id": "intruder"}).status_code
        == 422
    )
    assert client.get(f"/api/machines/{owner['machine']['id']}/sources").json()[0]["version"] == 1


@pytest.mark.parametrize(
    "data,name,mime",
    [
        (b"%PDF-this is not a readable PDF", "broken.pdf", "application/pdf"),
        (b"not an image", "broken.png", "image/png"),
        (b"\xff\x00", "broken.txt", "text/plain"),
    ],
)
def test_recognized_corrupt_files_keep_original_and_error(client, owner, data, name, mime):
    """Processing failures stay visible, with the exact original retained for inspection."""
    response = _upload(client, owner, name, data, mime)
    assert response.status_code == 200
    source = response.json()
    assert source["status"] == "error" and source["metadata"]["error"]
    assert client.get(f"/api/sources/{source['id']}/original").content == data
    assert str(settings.data_dir) not in response.text
