"""Index deletion, fresh snapshots and bounded concurrent access regressions."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from newton import retrieval
from newton.config import settings
from newton.db import Base
from newton.models import Company, Machine, Page, Source, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class _Item:
    def __init__(self, uuid, properties):
        self.uuid, self.properties = uuid, properties


class _Result:
    def __init__(self, objects):
        self.objects = objects


class FakeCollection:
    """Single-tenant, single-machine stand-in for the calls retrieval.py makes."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.query = self.data = self.tenants = self

    def exists(self, name):
        return True

    def with_tenant(self, name):
        return self

    def fetch_objects(self, **kwargs):
        return _Result([_Item(key, value) for key, value in self.objects.items()])

    def hybrid(self, **kwargs):
        return _Result([_Item(key, value) for key, value in self.objects.items()])

    def delete_by_id(self, uuid):
        self.objects.pop(uuid)

    def insert(self, uuid, properties, vector):
        assert uuid not in self.objects
        self.objects[uuid] = properties


class FakeClient:
    def __init__(self, collection):
        self.collections = self
        self._collection = collection

    def use(self, name):
        return self._collection


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/review.db")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    collection, embedded = FakeCollection(), []
    monkeypatch.setattr(settings, "data_dir", tmp_path / "private")

    @contextmanager
    def connection():
        yield FakeClient(collection)

    def embed(texts):
        embedded.extend(texts)
        return [[0.0] for _ in texts]

    monkeypatch.setattr(retrieval, "connection", connection)
    monkeypatch.setattr(retrieval, "embed", embed)
    with sessions() as db:
        user = User(email="reviewer@example.test", password_hash="x")
        db.add(user)
        db.flush()
        company = Company(owner_id=user.id, name="Synthetic")
        db.add(company)
        db.flush()
        machine = Machine(company_id=company.id, name="Pump")
        db.add(machine)
        db.flush()
        source = Source(
            company_id=company.id,
            machine_id=machine.id,
            filename="manual.txt",
            media_type="text/plain",
            sha256="0" * 64,
            storage_path="0" * 32 + ".bin",
            kind="document",
            status="ready",
        )
        db.add(source)
        db.flush()
        db.add(Page(source_id=source.id, number=1, text="SECRET torque 40 Nm"))
        db.commit()
        ids = (company.id, machine.id, source.id)
    yield sessions, collection, embedded, ids
    engine.dispose()


def search(db, company, machine, query="torque"):
    return retrieval.search(db, company, machine, query, datetime.now(UTC) + timedelta(minutes=10))


def test_empty_corpus_purges_last_indexed_document(world):
    sessions, collection, embedded, (company, machine, source) = world
    with sessions() as db:
        assert len(search(db, company, machine)) == 1
        db.query(Page).filter(Page.source_id == source).delete()
        db.delete(db.get(Source, source))
        db.commit()
        embedded.clear()
        assert search(db, company, machine) == []
    assert collection.objects == {}
    assert embedded == []


def test_busy_index_rejects_before_snapshot_or_embedding(world, monkeypatch):
    from fastapi import HTTPException
    from newton.index_lock import machine_index

    sessions, _, embedded, (company, machine, _) = world
    snapshots = []
    original = retrieval._chunks
    monkeypatch.setattr(retrieval, "_chunks", lambda *args: snapshots.append(1) or original(*args))
    with machine_index(company), sessions() as db:
        with pytest.raises(HTTPException) as error:
            search(db, company, machine)
        assert error.value.status_code == 409
    assert not snapshots and not embedded
    with sessions() as db:
        assert len(search(db, company, machine)) == 1


def test_snapshot_refreshes_cached_source_version(world):
    sessions, collection, _, (company, machine, source) = world
    with sessions() as first:
        stale = first.get(Source, source)
        assert stale.version == 1
        with sessions() as second:
            second.get(Source, source).version = 2
            second.commit()
        assert search(first, company, machine)[0]["source_version"] == 2
    assert all(p["source_version"] == 2 for p in collection.objects.values())


def test_expiring_run_sends_no_new_embedding_request(world):
    sessions, _, embedded, (company, machine, _) = world
    with sessions() as db, pytest.raises(ValueError, match="too little time"):
        retrieval.search(db, company, machine, "torque", datetime.now(UTC) + timedelta(seconds=60))
    assert embedded == []


def test_index_excerpt_is_reconstructed_from_authoritative_page(world, monkeypatch):
    """A derived index cannot attach arbitrary content to an otherwise valid source."""
    sessions, collection, _, (company, machine, _) = world
    with sessions() as db:
        search(db, company, machine)
        identifier, properties = next(iter(collection.objects.items()))
        forged = {**properties, "text": "Injected unrelated tenant's synthetic content"}
        monkeypatch.setattr(collection, "hybrid", lambda **kw: _Result([_Item(identifier, forged)]))
        result = search(db, company, machine)
    assert len(result) == 1
    assert result[0]["excerpt"] == "SECRET torque 40 Nm"
    assert result[0]["page"] == 1
    assert result[0]["original_sha256"] == "0" * 64
    assert result[0]["derivation"] == {
        "method": "page-text-chunk-v1",
        "page_id": properties["page_id"],
        "offset": 0,
        "max_characters": 1500,
        "trim_whitespace": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("page_id", "missing"),
        ("page_number", 2),
        ("offset", -1),
        ("offset", 1),
        ("offset", 1400),
        ("offset", "0"),
        ("offset", True),
    ],
)
def test_index_result_requires_valid_page_and_chunk(world, monkeypatch, field, value):
    """Index-provided page bindings and offsets cannot misattribute a source excerpt."""
    sessions, collection, _, (company, machine, _) = world
    with sessions() as db:
        search(db, company, machine)
        identifier, properties = next(iter(collection.objects.items()))
        forged = {**properties, field: value}
        monkeypatch.setattr(collection, "hybrid", lambda **kw: _Result([_Item(identifier, forged)]))
        assert search(db, company, machine) == []


def test_index_page_must_belong_to_the_checked_source(world, monkeypatch):
    """An existing page from another source cannot borrow an owned source identity."""
    sessions, collection, _, (company, machine, _) = world
    with sessions() as db:
        search(db, company, machine)
        identifier, properties = next(iter(collection.objects.items()))
        other = Source(
            company_id=company,
            machine_id=machine,
            filename="other.txt",
            media_type="text/plain",
            sha256="1" * 64,
            storage_path="other.bin",
            kind="document",
            status="ready",
        )
        db.add(other)
        db.flush()
        unrelated = Page(source_id=other.id, number=1, text="Unrelated synthetic content")
        db.add(unrelated)
        db.commit()
        forged = {**properties, "page_id": unrelated.id}
        monkeypatch.setattr(collection, "hybrid", lambda **kw: _Result([_Item(identifier, forged)]))
        assert search(db, company, machine) == []
