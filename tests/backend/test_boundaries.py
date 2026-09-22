"""Input and private storage boundaries exercised through the real router assembly."""

import io
import struct
import zlib

import pytest
from newton import db
from newton.config import settings
from newton.models import Source
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select


def _upload(client, owner, name, data, mime):
    return client.post(
        f"/api/machines/{owner['machine']['id']}/sources",
        files={
            "file": (name, data, mime),
        },
    )


@pytest.mark.parametrize(
    "filename,data,mime,status",
    [
        ("active.html", b"<script>alert(1)</script>", "text/html", 415),
        ("active.svg", b"<svg/>", "image/svg+xml", 415),
        ("wrong.pdf", b"not PDF", "application/pdf", 415),
        ("wrong.txt", b"text", "text/html", 415),
        ("empty.txt", b"", "text/plain", 422),
        pytest.param(
            "huge.txt", b"x" * (64 * 1024 * 1024 + 1), "text/plain", 413, id="oversized-64MiB"
        ),
    ],
)
def test_upload_rejections_do_not_change_context_or_create_files(
    client,
    owner,
    filename,
    data,
    mime,
    status,
):
    """Unsupported, empty and oversized uploads fail before authoritative changes."""
    response = _upload(client, owner, filename, data, mime)
    assert response.status_code == status
    path = f"/api/machines/{owner['machine']['id']}"
    assert client.get(path).json()["context_version"] == 1
    assert client.get(path + "/sources").json() == []
    assert not list(settings.data_dir.rglob("*.bin"))


def test_filename_is_safe_and_original_html_text_is_an_attachment(client, owner):
    """Untrusted filenames cannot traverse directories or become active response headers."""
    data = b"<html><script>synthetic()</script></html>"
    response = _upload(client, owner, '..\\..\\evil"\r\nheader.md', data, "text/markdown")
    source = response.json()
    assert response.status_code == 200
    assert all(character not in source["filename"] for character in ("/", "\\", '"', "\r", "\n"))
    original = client.get(f"/api/sources/{source['id']}/original")
    assert original.content == data and "attachment" in original.headers["content-disposition"]
    assert "sandbox" in original.headers["content-security-policy"]
    assert original.headers["content-type"].startswith("text/markdown")


def test_large_image_dimensions_and_spoofed_image_are_errors(client, owner, png_bytes):
    """An image bomb is rejected before allocating pixels and format mismatches stay unready."""
    data = bytearray(png_bytes)
    data[16:24] = struct.pack(">II", 5000, 5000)
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    bomb = _upload(client, owner, "bomb.png", bytes(data), "image/png").json()
    assert bomb["status"] == "error" and "pixel" in bomb["metadata"]["error"]
    spoofed = _upload(client, owner, "wrong.jpg", png_bytes, "image/jpeg").json()
    assert spoofed["status"] == "error"
    assert client.get(f"/api/sources/{bomb['id']}/pages/1/image").status_code == 404


def test_animated_image_is_visible_error(client, owner):
    """Multi-frame inputs are not silently reduced to a misleading single frame."""
    stream = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        stream,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
        loop=0,
    )
    source = _upload(client, owner, "animation.webp", stream.getvalue(), "image/webp").json()
    assert source["status"] == "error" and "Animated" in source["metadata"]["error"]


def test_pdf_page_limit_and_encryption_are_explicit(client, owner):
    """Bounded extraction does not pretend encrypted or excessive PDFs are ready."""
    writer, stream = PdfWriter(), io.BytesIO()
    for _ in range(251):
        writer.add_blank_page(width=10, height=10)
    writer.write(stream)
    source = _upload(client, owner, "many.pdf", stream.getvalue(), "application/pdf").json()
    assert source["status"] == "error" and "250" in source["metadata"]["error"]
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=10, height=10)
    writer.encrypt("synthetic PDF password")
    writer.write(stream)
    source = _upload(client, owner, "encrypted.pdf", stream.getvalue(), "application/pdf").json()
    assert source["status"] == "error"
    assert "encrypted" in source["metadata"]["error"]


@pytest.mark.parametrize("mode", ["tampered", "symlink", "traversal"])
def test_storage_integrity_and_path_boundary(client, owner, tmp_path, mode):
    """Even corrupt internal storage references cannot expose arbitrary local files."""
    source = _upload(client, owner, "safe.txt", b"synthetic original", "text/plain").json()
    with db.SessionLocal() as session:
        stored = session.get(Source, source["id"])
        path = settings.data_dir / "originals" / stored.storage_path
        if mode == "tampered":
            path.chmod(0o600)
            path.write_bytes(b"changed")
        elif mode == "symlink":
            target = tmp_path / "private-not-source.txt"
            target.write_bytes(b"never disclose this synthetic secret")
            path.unlink()
            path.symlink_to(target)
        else:
            stored.storage_path = "../../private-not-source.txt"
            session.commit()
    response = client.get(f"/api/sources/{source['id']}/original")
    assert response.status_code == 503
    assert "never disclose" not in response.text and str(tmp_path) not in response.text


def test_upload_database_failure_cleans_private_file(client, owner, monkeypatch):
    """A failed insert cannot leave orphan originals or advance the context version."""
    from sqlalchemy.orm import Session

    with monkeypatch.context() as context:

        def fail_commit(self):
            raise RuntimeError("synthetic transaction failure")

        context.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic transaction failure"):
            _upload(client, owner, "safe.txt", b"synthetic original", "text/plain")
    assert not list(settings.data_dir.rglob("*.bin"))
    with db.SessionLocal() as session:
        assert list(session.scalars(select(Source))) == []
    assert client.get(f"/api/machines/{owner['machine']['id']}").json()["context_version"] == 1


def test_delete_database_failure_restores_original(client, owner, monkeypatch):
    """A failed delete restores both the authoritative source and its staged private original."""
    from sqlalchemy.orm import Session

    data = b"synthetic original"
    source = _upload(client, owner, "safe.txt", data, "text/plain").json()
    path = f"/api/sources/{source['id']}"
    with monkeypatch.context() as context:

        def fail_commit(self):
            raise RuntimeError("synthetic transaction failure")

        context.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic transaction failure"):
            client.delete(path)
    assert client.get(path + "/original").content == data
    assert client.get(f"/api/machines/{owner['machine']['id']}").json()["context_version"] == 2
    assert not list(settings.data_dir.rglob("*.deleting"))
