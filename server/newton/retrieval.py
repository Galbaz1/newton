"""Rebuildable, tenant-scoped Weaviate retrieval with authoritative result checks."""

import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import weaviate
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter
from weaviate.classes.tenants import Tenant
from weaviate.exceptions import WeaviateBaseError

from newton.config import settings
from newton.index_lock import machine_index
from newton.models import Page, Source
from newton.providers import embed

COLLECTION = "NewtonTextPages"
_schema_lock = threading.Lock()


@contextmanager
def connection():
    """Open a request-owned local index connection and always release it."""
    with weaviate.connect_to_local(
        host=settings.weaviate_host,
        port=settings.weaviate_http_port,
        grpc_port=settings.weaviate_grpc_port,
        auth_credentials=Auth.api_key(settings.weaviate_api_key),
    ) as client:
        yield client


def scope_filter(machine_id: str):
    """Select one machine and its company library inside an authorized tenant."""
    return Filter.any_of(
        [
            Filter.by_property("machine_id").equal(machine_id),
            Filter.by_property("machine_id").equal("company"),
        ]
    )


def initialize() -> None:
    """Create the versioned text index schema without enabling automatic tenants.

    Database ownership is enforced before this module is called. Weaviate's
    tenant partition is an additional boundary, not an authorization decision.
    """
    with _schema_lock, connection() as client:
        if client.collections.exists(COLLECTION):
            return
        client.collections.create(
            COLLECTION,
            vector_config=Configure.Vectors.self_provided(name="text"),
            multi_tenancy_config=Configure.multi_tenancy(enabled=True, auto_tenant_creation=False),
            properties=[
                Property(name=name, data_type=DataType.TEXT)
                for name in ["machine_id", "source_id", "page_id", "text", "filename"]
            ]
            + [
                Property(name=name, data_type=DataType.INT)
                for name in ["source_version", "page_number", "offset"]
            ],
        )


def _chunks(db: Session, company_id: str, machine_id: str) -> list[dict]:
    pairs = db.execute(
        select(Page, Source)
        .join(Source, Page.source_id == Source.id)
        .where(
            Source.company_id == company_id,
            or_(Source.machine_id == machine_id, Source.machine_id.is_(None)),
            Source.data_class.in_(["original", "derived"]),
            Source.status == "ready",
            Source.kind == "document",
        )
        .order_by(Source.id, Page.number)
    ).all()
    chunks = []
    for page, source in pairs:
        for offset in range(0, len(page.text), 1400):
            text = page.text[offset : offset + 1500].strip()
            if not text:
                continue
            identity = f"newton:text-embedding-3-small:{page.id}:{source.version}:{offset}"
            chunks.append(
                {
                    "uuid": str(uuid5(NAMESPACE_URL, identity)),
                    "properties": {
                        "machine_id": source.machine_id or "company",
                        "source_id": source.id,
                        "page_id": page.id,
                        "text": text,
                        "filename": source.filename,
                        "source_version": source.version,
                        "page_number": page.number,
                        "offset": offset,
                    },
                }
            )
    if len(chunks) > 2000:
        raise ValueError(
            "This machine exceeds the local 2000-snippet index limit; split its corpus."
        )
    return chunks


def check_deadline(deadline: datetime) -> None:
    """Refuse another external call when its timeout could exceed the run lease."""
    if datetime.now(UTC) + timedelta(seconds=180) >= deadline:
        raise ValueError("The answering run has too little time left for another provider call.")


def _sync(
    collection, chunks: list[dict], machine_id: str, deadline: datetime, progress=None
) -> None:
    existing = collection.query.fetch_objects(
        filters=scope_filter(machine_id),
        limit=10000,
        return_properties=["source_id"],
    ).objects
    known = {str(item.uuid) for item in existing}
    wanted = {chunk["uuid"] for chunk in chunks}
    for obsolete in known - wanted:
        collection.data.delete_by_id(obsolete)
    missing = [chunk for chunk in chunks if chunk["uuid"] not in known]
    if progress:
        progress(len(chunks) - len(missing), len(chunks))
    for start in range(0, len(missing), 64):
        batch = missing[start : start + 64]
        check_deadline(deadline)
        vectors = embed([chunk["properties"]["text"] for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            collection.data.insert(
                uuid=chunk["uuid"], properties=chunk["properties"], vector={"text": vector}
            )
        if progress:
            progress(len(chunks) - len(missing) + start + len(batch), len(chunks))


def search(
    db: Session, company_id: str, machine_id: str, query: str, deadline: datetime
) -> list[dict]:
    """Retrieve source snippets only from the authorized machine's current corpus.

    Args:
        db: Request-scoped authoritative SQL session.
        company_id: Company already authorized by the caller.
        machine_id: Machine already checked as belonging to that company.
        query: User question used for hybrid lexical/vector search.
        deadline: Active run lease; leave room for each bounded provider call.

    Returns:
        Up to six evidence records, each validated against current source state.

    Raises:
        ValueError: Corpus exceeds the explicit local bound or query is oversized.
        ProviderError: Embedding generation fails; there is no hidden fallback.
        BudgetExceeded: Embedding cost cannot be admitted under the shared cap.
    """
    if len(query.encode()) > 6000:
        raise ValueError("Question is too long for the retrieval query.")
    with machine_index(company_id), connection() as client:
        # Read after locking so a waiting caller cannot roll back a newer index.
        db.expire_all()
        chunks = _chunks(db, company_id, machine_id)
        base = client.collections.use(COLLECTION)
        if not base.tenants.exists(company_id):
            if not chunks:
                return []
            try:
                base.tenants.create([Tenant(name=company_id)])
            except WeaviateBaseError:
                # Different machines in one company may create its tenant together.
                if not base.tenants.exists(company_id):
                    raise
        collection = base.with_tenant(company_id)
        _sync(collection, chunks, machine_id, deadline)
        if not chunks:
            return []
        check_deadline(deadline)
        vector = embed([query])[0]
        results = collection.query.hybrid(
            query=query,
            vector=vector,
            target_vector="text",
            alpha=0.5,
            limit=10,
            filters=scope_filter(machine_id),
        ).objects
    return _evidence(db, results, company_id, machine_id)


def _evidence(db: Session, results: list, company_id: str, machine_id: str) -> list[dict]:
    """Use index results only as locators for current, authorized SQL page excerpts."""
    evidence = []
    for result in results:
        props = result.properties
        source = db.get(Source, props["source_id"], populate_existing=True)
        page = db.get(Page, props["page_id"], populate_existing=True)
        offset = props["offset"]
        if (
            source is None
            or page is None
            or page.source_id != source.id
            or page.number != props["page_number"]
            or source.company_id != company_id
            or source.machine_id not in {None, machine_id}
            or source.data_class not in {"original", "derived"}
            or source.version != props["source_version"]
            or source.status != "ready"
            or source.kind != "document"
            or type(offset) is not int
            or offset < 0
            or offset >= len(page.text)
            or offset % 1400 != 0
        ):
            continue
        excerpt = page.text[offset : offset + 1500].strip()
        if not excerpt:
            continue
        evidence.append(
            {
                "id": f"E{len(evidence) + 1}",
                "source_id": source.id,
                "filename": source.filename,
                "page": page.number,
                "excerpt": excerpt,
                "revision": source.revision,
                "source_version": source.version,
                "kind": "document",
                "original_sha256": source.sha256,
                "derivation": {
                    "method": "page-text-chunk-v1",
                    "page_id": page.id,
                    "offset": offset,
                    "max_characters": 1500,
                    "trim_whitespace": True,
                },
                "original_url": f"/api/sources/{source.id}/original",
                "page_image_url": (f"/api/sources/{source.id}/pages/{page.number}/image")
                if source.media_type == "application/pdf"
                else None,
            }
        )
        if len(evidence) == 6:
            break
    return evidence


def remove_source(company_id: str, source_id: str) -> None:
    """Remove derived source text before committing deletion of its original.

    The caller must authorize the source and hold its machine index lock. A
    service failure aborts deletion; authoritative rows/originals remain intact.
    """
    with connection() as client:
        for name in (COLLECTION, "NewtonVisualPagesV1"):
            if not client.collections.exists(name):
                continue
            base = client.collections.use(name)
            if base.tenants.exists(company_id):
                result = base.with_tenant(company_id).data.delete_many(
                    where=Filter.by_property("source_id").equal(source_id)
                )
                if result.failed:
                    raise ValueError("Derived source deletion did not complete.")
