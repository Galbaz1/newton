"""Shared SQL evidence scope; company library access cannot cross tenant boundaries."""

from sqlalchemy import or_, select

from .models import Machine, Source


def source_selection(machine: Machine):
    """Select real/derived sources for this machine and its own company library."""
    return select(Source).where(
        Source.company_id == machine.company_id,
        or_(Source.machine_id == machine.id, Source.machine_id.is_(None)),
        Source.data_class.in_(["original", "derived"]),
    )


def bump_source_context(db, source: Source) -> None:
    """Invalidate every affected machine when a company-library source changes."""
    from .companies import bump_context

    ids = (
        [source.machine_id]
        if source.machine_id
        else db.scalars(select(Machine.id).where(Machine.company_id == source.company_id)).all()
    )
    for machine_id in ids:
        bump_context(db, machine_id)
