"""Synthetic route fixtures; no production data, services or provider calls."""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from newton import auth, companies, db, sources
from newton.config import settings
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Assemble only the worker routers with an isolated SQLite database and private root."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.sqlite'}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "data_dir", tmp_path / "private")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(sources, "remove_index_source", lambda *args: None)
    db.init_db()
    application = FastAPI()
    for router in (auth.router, companies.router, sources.router):
        application.include_router(router, prefix="/api")
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    """Provide an HTTP client without a network listener."""
    with TestClient(app) as connection:
        yield connection


@pytest.fixture
def owner(client):
    """Create an explicitly synthetic owner/company/machine through real routes."""
    user = client.post(
        "/api/auth/register",
        json={"email": "owner@example.test", "password": "synthetic password 123"},
    )
    assert user.status_code == 200
    company = client.post("/api/companies", json={"name": "Synthetic company"}).json()
    machine = client.post(
        f"/api/companies/{company['id']}/machines",
        json={
            "name": "Synthetic test machine",
            "manufacturer": "Fixture",
            "model": "SYNTH-1",
            "description": "No connection to physical equipment",
        },
    ).json()
    return {"user": user.json(), "company": company, "machine": machine}


@pytest.fixture
def pdf_bytes():
    """Build a tiny synthetic PDF with one text page and one blank/scanned-style page."""
    writer = PdfWriter()
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
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (SYNTHETIC maintenance instructions) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=320, height=240)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.fixture
def png_bytes():
    """Build a small synthetic image without relying on downloaded assets."""
    result = io.BytesIO()
    Image.new("RGB", (16, 12), color=(0, 100, 150)).save(result, format="PNG")
    return result.getvalue()
