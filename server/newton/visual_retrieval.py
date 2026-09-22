"""Tenant-scoped ColQwen page retrieval with SQL-checked original provenance."""

import hashlib
import threading
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from weaviate.classes.config import Configure, DataType, Property, Tokenization, VectorDistances
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.classes.tenants import Tenant
from weaviate.exceptions import WeaviateBaseError

from newton import visual_encoder
from newton._storage import read_original
from newton.config import settings
from newton.documents import render_page
from newton.index_lock import machine_index
from newton.models import Page, Source
from newton.retrieval import check_deadline, connection

COLLECTION = "NewtonVisualPagesV1"
MAX_PAGES = 512
_schema_lock = threading.Lock()


def scope_filter(machine_id: str):
    """Select one machine and its company library inside an authorized tenant."""
    return Filter.any_of(
        [
            Filter.by_property("machine_id").equal(machine_id),
            Filter.by_property("machine_id").equal("company"),
        ]
    )


def initialize() -> None:
    """Create a genuine multi-vector index when the private encoder is configured."""
    if not settings.visual_encoder_url:
        return
    with _schema_lock, connection() as client:
        if client.collections.exists(COLLECTION):
            return
        client.collections.create(
            COLLECTION,
            vector_config=Configure.MultiVectors.self_provided(
                name="visual",
                multi_vector_config=Configure.VectorIndex.MultiVector.multi_vector(),
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE
                ),
            ),
            multi_tenancy_config=Configure.multi_tenancy(enabled=True, auto_tenant_creation=False),
            properties=[
                Property(name=name, data_type=DataType.TEXT, tokenization=Tokenization.FIELD)
                for name in ["machine_id", "source_id", "page_id", "render_sha256"]
            ]
            + [
                Property(name=name, data_type=DataType.INT)
                for name in ["source_version", "page_number"]
            ],
        )


def _pages(db: Session, company_id: str, machine_id: str) -> list:
    pairs = list(
        db.execute(
            select(Page, Source)
            .join(Source, Source.id == Page.source_id)
            .where(
                Source.company_id == company_id,
                or_(Source.machine_id == machine_id, Source.machine_id.is_(None)),
                Source.data_class.in_(["original", "derived"]),
                Source.status.in_(["ready", "needs_text"]),
                or_(Source.kind == "image", Source.media_type == "application/pdf"),
            )
            .order_by(Source.id, Page.number)
            .limit(MAX_PAGES + 1)
        )
    )
    if len(pairs) > MAX_PAGES:
        raise ValueError("Visual retrieval is limited to 512 pages per machine; narrow its corpus.")
    return pairs


def _identity(page: Page, source: Source) -> str:
    key = f"{visual_encoder.REVISION}:{visual_encoder.RENDER_VERSION}:{page.id}:{source.version}"
    return str(uuid5(NAMESPACE_URL, key))


def _render(source: Source, number: int) -> bytes:
    return visual_encoder.prepare_page(
        render_page(read_original(source), source.media_type, number)
    )


def _sync(collection, pairs: list, machine_id: str, deadline: datetime, progress=None) -> None:
    existing = collection.query.fetch_objects(
        filters=scope_filter(machine_id),
        limit=10000,
        return_properties=["source_id"],
    ).objects
    known = {str(item.uuid) for item in existing}
    wanted = {_identity(page, source) for page, source in pairs}
    for identifier in known - wanted:
        collection.data.delete_by_id(identifier)
    completed = len(known & wanted)
    if progress:
        progress(completed, len(pairs))
    for page, source in pairs:
        identifier = _identity(page, source)
        if identifier in known:
            continue
        check_deadline(deadline)
        png = _render(source, page.number)
        vectors = visual_encoder.encode_page(png)
        collection.data.insert(
            uuid=identifier,
            properties={
                "machine_id": source.machine_id or "company",
                "source_id": source.id,
                "page_id": page.id,
                "source_version": source.version,
                "page_number": page.number,
                "render_sha256": hashlib.sha256(png).hexdigest(),
            },
            vector={"visual": vectors},
        )
        completed += 1
        if progress:
            progress(completed, len(pairs))


def _record(source: Source, page: Page, props: dict, distance: float) -> dict:
    return {
        "source_id": source.id,
        "filename": source.filename,
        "page": page.number,
        "excerpt": "Original page supplied to the answering model; no OCR or caption substituted.",
        "revision": source.revision,
        "source_version": source.version,
        "kind": "image",
        "original_url": f"/api/sources/{source.id}/original",
        "page_image_url": f"/api/sources/{source.id}/pages/{page.number}/image",
        "retrieval": {
            "method": "colqwen-maxsim",
            "model": visual_encoder.MODEL,
            "revision": visual_encoder.REVISION,
            "distance": distance,
            "score_is_confidence": False,
        },
        "original_sha256": source.sha256,
        "render_sha256": props["render_sha256"],
        "render_version": visual_encoder.RENDER_VERSION,
    }


def _evidence(db: Session, results: list, company_id: str, machine_id: str) -> tuple:
    records, images = [], []
    for result in results:
        props = result.properties
        source = db.get(Source, props["source_id"], populate_existing=True)
        page = db.get(Page, props["page_id"], populate_existing=True)
        if (
            source is None
            or page is None
            or page.source_id != source.id
            or source.company_id != company_id
            or source.machine_id not in {None, machine_id}
            or source.data_class not in {"original", "derived"}
            or source.version != props["source_version"]
            or page.number != props["page_number"]
            or source.status not in {"ready", "needs_text"}
            or not (source.kind == "image" or source.media_type == "application/pdf")
        ):
            continue
        png = _render(source, page.number)
        if hashlib.sha256(png).hexdigest() != props["render_sha256"]:
            raise ValueError("Visual page rendering changed; its derived index must be rebuilt.")
        records.append(_record(source, page, props, result.metadata.distance))
        images.append(png)
        if len(records) == 3:
            break
    return records, images


def search(
    db: Session, company_id: str, machine_id: str, query: str, deadline: datetime
) -> tuple[list[dict], list[bytes]]:
    """Return up to three retrieved page records and corresponding bounded PNGs.

    Args:
        db: Authoritative SQL session; caller has checked current access.
        company_id: Authorized company, used as the Weaviate tenant.
        machine_id: Machine belonging to that company.
        query: Bounded investigation question.
        deadline: Run deadline checked before encoder calls.

    Returns:
        Evidence records without citation IDs and matching PNG bytes. Empty when
        no encoder is configured or no visual pages exist. A retrieval score is
        not confidence; the model must inspect relevance and may abstain.

    Raises:
        ValueError: Corpus bounds, encoder or derived provenance check fails.
        WeaviateBaseError: The derived index is unavailable.
    """
    if not settings.visual_encoder_url:
        return [], []
    with machine_index(company_id), connection() as client:
        db.expire_all()
        pairs = _pages(db, company_id, machine_id)
        base = client.collections.use(COLLECTION)
        if not base.tenants.exists(company_id):
            if not pairs:
                return [], []
            try:
                base.tenants.create([Tenant(name=company_id)])
            except WeaviateBaseError:
                if not base.tenants.exists(company_id):
                    raise
        collection = base.with_tenant(company_id)
        _sync(collection, pairs, machine_id, deadline)
        if not pairs:
            return [], []
        check_deadline(deadline)
        matrix = visual_encoder.encode_query(query)
        results = collection.query.near_vector(
            matrix,
            target_vector="visual",
            limit=6,
            filters=scope_filter(machine_id),
            return_metadata=MetadataQuery(distance=True),
        ).objects
        return _evidence(db, results, company_id, machine_id)
