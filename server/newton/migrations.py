"""Small additive migration for the local PostgreSQL prototype.

Operators back up the database before upgrading. No originals or historical answer
snapshots are rewritten. SQLite tests create the current schema from scratch.
"""

from sqlalchemy import inspect, text


def migrate_sources(engine) -> None:
    """Allow company-library sources and explicitly classify synthetic evidence.

    Args:
        engine: Application SQLAlchemy engine; existing PostgreSQL schema supported.
    """
    schema = inspect(engine)
    if "sources" not in schema.get_table_names():
        return
    columns = {c["name"]: c for c in schema.get_columns("sources")}
    if "data_class" in columns and columns["machine_id"]["nullable"]:
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Upgrade existing local data using PostgreSQL and a database backup")
    constraints = schema.get_check_constraints("sources")
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '30s'"))
        connection.execute(text("ALTER TABLE sources ALTER COLUMN machine_id DROP NOT NULL"))
        if "data_class" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE sources ADD COLUMN data_class VARCHAR(20) "
                    "NOT NULL DEFAULT 'original'"
                )
            )
        for constraint in constraints:
            if "kind" in constraint["sqltext"] or "status" in constraint["sqltext"]:
                name = engine.dialect.identifier_preparer.quote(constraint["name"])
                connection.execute(text(f"ALTER TABLE sources DROP CONSTRAINT {name}"))
        connection.execute(
            text(
                "ALTER TABLE sources ADD CONSTRAINT source_kind_allowed CHECK "
                "(kind IN ('document','image','timeseries','annotation'))"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE sources ADD CONSTRAINT source_status_allowed CHECK "
                "(status IN ('ready','needs_mapping','needs_text','error','quarantined'))"
            )
        )
