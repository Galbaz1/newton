"""Resumable source indexing, independent of the ten-minute answering lease."""

from datetime import UTC, datetime, timedelta

from weaviate.classes.tenants import Tenant

from . import retrieval, visual_retrieval
from .config import settings
from .index_lock import machine_index
from .onboarding_state import checkpoint


def index_sources(db, run, check_running) -> None:
    """Index all accepted text/pages with durable per-batch/page progress.

    Existing deterministic index identities are reused after interruption. A page
    failure stops this phase visibly; completed pages are not silently excluded.
    """
    deadline = datetime.now(UTC) + timedelta(hours=2)
    completed = list(run.state.get("indexed_machines", []))
    for reference, machine_id in run.state.get("assets", {}).items():
        check_running(db, run)
        if machine_id in completed:
            continue
        with machine_index(run.company_id), retrieval.connection() as client:
            for kind, module, records in (
                ("tekst", retrieval, retrieval._chunks(db, run.company_id, machine_id)),
                (
                    "visueel",
                    visual_retrieval,
                    visual_retrieval._pages(db, run.company_id, machine_id)
                    if settings.visual_encoder_url
                    else [],
                ),
            ):
                if not records:
                    continue
                base = client.collections.use(module.COLLECTION)
                if not base.tenants.exists(run.company_id):
                    base.tenants.create([Tenant(name=run.company_id)])
                collection = base.with_tenant(run.company_id)

                def progress(done, total, reference=reference, kind=kind):
                    check_running(db, run)
                    run.stage = f"Indexeren {reference} · {kind} {done}/{total}"
                    checkpoint(db, run, "index", run.stage)

                module._sync(collection, records, machine_id, deadline, progress)
        completed.append(machine_id)
        checkpoint(
            db,
            run,
            "index",
            f"Installatie {reference}: indexering voltooid.",
            indexed_machines=completed,
        )
