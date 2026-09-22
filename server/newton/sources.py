"""Owner-scoped source intake and inspection; original bytes are immutable until deletion.

Unsupported/oversized uploads return 415/413. Recognized files with extraction or
observation errors retain their original with status=error and metadata.error.
Invalid mapping fields return 422 without changes; valid mappings with bad data
persist an error state. Unready series return 409. Missing private bytes return 503.
"""

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from weaviate.exceptions import WeaviateBaseError

from . import documents, measurements
from ._schemas import SourcePatch, project, source_json
from ._storage import (
    read_original,
    read_upload,
    remove_original,
    save_original,
    stage_removal,
    undo_removal,
)
from .db import get_db
from .evidence import readiness as evidence_readiness
from .index_lock import machine_index
from .models import Page, Source, User
from .retrieval import remove_source as remove_index_source
from .security import current_user, require_company, require_machine, require_source
from .source_scope import bump_source_context

router = APIRouter(tags=["sources"])
_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


@router.get("/machines/{machine_id}/sources")
def list_sources(
    machine_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """List all intake states for an owned machine, without private filesystem paths."""
    machine = require_machine(db, user, machine_id)
    rows = db.scalars(
        select(Source)
        .where(
            Source.company_id == machine.company_id,
            (Source.machine_id == machine.id) | Source.machine_id.is_(None),
        )
        .order_by(Source.created_at, Source.id)
    )
    return [source_json(row) for row in rows]


@router.post("/machines/{machine_id}/sources")
def upload_source(
    machine_id: str,
    file: UploadFile = File(...),
    revision: str = Form("", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Persist an exact original, extracted pages and one machine context increment."""
    machine = require_machine(db, user, machine_id)
    data, filename, media_type, kind = read_upload(file)
    if kind == "timeseries":
        status, metadata = measurements.inspect_csv(data)
        pages = []
    else:
        status, metadata, pages = documents.extract_document(data, media_type)
    storage_path = save_original(data)
    source = Source(
        company_id=machine.company_id,
        machine_id=machine.id,
        filename=filename,
        media_type=media_type,
        sha256=hashlib.sha256(data).hexdigest(),
        kind=kind,
        storage_path=storage_path,
        status=status,
        revision=revision,
        metadata_json=metadata,
    )
    try:
        db.add(source)
        db.flush()
        db.add_all(
            Page(source_id=source.id, number=number, text=text)
            for number, text in enumerate(pages, 1)
        )
        bump_source_context(db, source)
        db.commit()
    except Exception:
        db.rollback()
        remove_original(storage_path)
        raise
    return source_json(source)


def _apply_mapping(source: Source, mapping) -> None:
    if source.kind != "timeseries":
        raise HTTPException(422, "Only CSV sources accept measurement mappings")
    original = read_original(source)
    measurements.validate_mapping(original, mapping)
    source.mapping = mapping.model_dump()
    status, metadata = measurements.inspect_csv(original)
    if status != "error":
        try:
            measurements.extract_series(original, source.id, source.mapping)
            status = "ready"
        except ValueError as error:
            status, metadata = "error", {**metadata, "error": str(error)}
    retained = {key: value for key, value in source.metadata_json.items() if key != "error"}
    retained["time_basis"] = source.mapping.get("time_basis", "absolute")
    if "channels" in retained:
        retained["channels"] = [
            {**channel, "unit": source.mapping["unit"]}
            if channel["column"] == source.mapping["value_column"]
            else channel
            for channel in retained["channels"]
        ]
    source.status, source.metadata_json = status, {**retained, **metadata}


@router.patch("/sources/{source_id}")
def patch_source(
    source_id: str,
    data: SourcePatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Correct revision/mapping, preserving bytes/hash and advancing both versions."""
    source = require_source(db, user, source_id)
    if data.mapping is not None:
        _apply_mapping(source, data.mapping)
    if data.revision is not None:
        source.revision = data.revision
    db.execute(update(Source).where(Source.id == source.id).values(version=Source.version + 1))
    bump_source_context(db, source)
    db.commit()
    db.refresh(source)
    return source_json(source)


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Remove source/pages/private bytes and invalidate the machine's evidence context."""
    source = require_source(db, user, source_id)
    with machine_index(source.company_id):
        db.expire_all()
        source = require_source(db, user, source_id)
        try:
            remove_index_source(source.company_id, source.id)
        except WeaviateBaseError, ValueError:
            raise HTTPException(
                503, "Evidence index cleanup failed; source deletion was not committed."
            ) from None
        return _delete_original(db, source)


def _delete_original(db: Session, source: Source) -> dict:
    temporary = stage_removal(source.storage_path)
    try:
        db.execute(delete(Page).where(Page.source_id == source.id))
        bump_source_context(db, source)
        db.delete(source)
        db.commit()
    except Exception:
        db.rollback()
        undo_removal(temporary, source.storage_path)
        raise
    if temporary is not None:
        try:
            temporary.unlink()
        except OSError:
            raise HTTPException(503, "Private file cleanup failed") from None
    return {"ok": True}


@router.get("/sources/{source_id}/original")
def original(source_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Download verified exact original bytes as a safe private attachment."""
    source = require_source(db, user, source_id)
    headers = {
        **_PRIVATE_HEADERS,
        "Content-Disposition": f'attachment; filename="{source.filename}"',
    }
    return Response(read_original(source), media_type=source.media_type, headers=headers)


@router.get("/sources/{source_id}/pages")
def pages(source_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Return literal extracted text as JSON after source ownership checks."""
    source = require_source(db, user, source_id)
    rows = db.scalars(select(Page).where(Page.source_id == source.id).order_by(Page.number))
    return [project(row, "id number text") for row in rows]


@router.get("/sources/{source_id}/pages/{number}/image")
def page_image(
    source_id: str, number: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Render an authorized PDF/image page to an inert, bounded PNG preview."""
    source = require_source(db, user, source_id)
    page = db.scalar(select(Page.id).where(Page.source_id == source.id, Page.number == number))
    if page is None:
        raise HTTPException(404, "Page not found")
    data = documents.render_page(read_original(source), source.media_type, number)
    return Response(data, media_type="image/png", headers=_PRIVATE_HEADERS)


@router.get("/sources/{source_id}/series")
def series(
    source_id: str,
    channel: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Return original observations only when every mapped row is valid and ready."""
    source = require_source(db, user, source_id)
    if source.kind != "timeseries":
        raise HTTPException(404, "Measurement series not found")
    if source.status != "ready" or source.mapping is None:
        raise HTTPException(
            409, source.metadata_json.get("error", "Map the CSV before viewing series")
        )
    mapping = dict(source.mapping)
    if channel:
        channels = source.metadata_json.get("channels", [])
        chosen = next((c for c in channels if c["column"] == channel), None)
        if chosen is None:
            raise HTTPException(422, "Unknown measurement channel")
        mapping.update(value_column=channel, unit=chosen["unit"])
    try:
        return measurements.extract_series(read_original(source), source.id, mapping, start, end)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/machines/{machine_id}/readiness")
def readiness(machine_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Explain evidence readiness after checking ownership of the machine."""
    return evidence_readiness(db, require_machine(db, user, machine_id))


@router.get("/companies/{company_id}/sources")
def company_sources(
    company_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Inspect every owned source, including quarantined and synthetic material."""
    company = require_company(db, user, company_id)
    return [
        source_json(s) for s in db.scalars(select(Source).where(Source.company_id == company.id))
    ]


@router.get("/sources/{source_id}/annotations")
def annotations(source_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Return source label assertions without inferring unannotated periods are normal."""
    source = require_source(db, user, source_id)
    if source.kind != "annotation":
        raise HTTPException(404, "Annotation source not found")
    return {
        "source_id": source.id,
        "original_sha256": source.sha256,
        **source.metadata_json.get("annotations", {}),
    }
