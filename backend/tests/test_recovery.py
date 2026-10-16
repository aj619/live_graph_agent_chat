"""Tests for startup recovery of interrupted insertions (plan §6.5, app.recovery).

app.recovery opens sessions through `SessionLocal` from app.db, and importing
app.db or app.recovery needs an app.config that can load. These tests must not
read the real repo env files, so the fixture below puts a stub `app.config` into
sys.modules for the duration of the import only. The stub holds placeholder
values and never reads a file. The real MySQL engine is built lazily and never
connects. The tests then redirect `recovery_module.SessionLocal` to an in-memory
SQLite database, so every session runs against SQLite and no MySQL server is
touched. Each test gets a fresh engine and fresh tables.

No test here is marked `integration`. The tests need no live service.
"""

import importlib
import sys
import uuid
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy
from fakes import FakeGraphService
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The modules this file imports. Any that were not loaded before the fixture ran
# are removed again afterwards, so the stub-configured copies never leak out.
_APP_MODULES = ("app.recovery", "app.registry", "app.db", "app.graph")


def _stub_config() -> ModuleType:
    """Build a placeholder app.config. It has only what app.db, app.graph and app.registry read."""
    config = ModuleType("app.config")
    placeholder_settings = type(
        "PlaceholderSettings",
        (),
        {
            "MYSQL_USER": "placeholder_user",
            "MYSQL_PASSWORD": "placeholder-mysql-password",
            "MYSQL_HOST": "placeholder-host",
            "MYSQL_PORT": 3306,
            "MYSQL_DATABASE": "placeholder_db",
            "DATA_DIR": "./data",
        },
    )()
    setattr(config, "settings", placeholder_settings)  # noqa: B010 - ModuleType attrs are dynamic
    setattr(config, "Settings", type("PlaceholderSettingsType", (), {}))  # noqa: B010
    return config


@pytest.fixture
def recovery_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Yield app.recovery imported against the stub config, then drop what this import added."""
    already_loaded = {name for name in _APP_MODULES if name in sys.modules}
    monkeypatch.setitem(sys.modules, "app.config", _stub_config())
    module = importlib.import_module("app.recovery")
    yield module
    for name in _APP_MODULES:
        if name not in already_loaded:
            sys.modules.pop(name, None)


@pytest.fixture
def session_factory(
    recovery_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sessionmaker[Session]]:
    """Give each test a fresh in-memory SQLite database and point app.recovery at it."""
    from app.db import Base

    engine = sqlalchemy.create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(recovery_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _make_document(session: Session, doc_id: uuid.UUID, status_after: str | None = None) -> None:
    """Create one document row through the registry. Optionally set its status afterwards."""
    from app.registry import create_document, set_document_status

    create_document(
        session,
        doc_id=doc_id,
        filename="a.txt",
        stored_name=f"{doc_id}.txt",
        size_bytes=10,
    )
    if status_after is not None:
        set_document_status(session, doc_id, status_after)


def _track(session: Session, doc_id: uuid.UUID, episode: uuid.UUID, index: int) -> None:
    """Record one pending tracking row through the registry."""
    from app.registry import record_pending_chunk

    record_pending_chunk(session, episode_uuid=episode, doc_id=doc_id, chunk_index=index)


def _chunk_rows(session: Session, doc_id: uuid.UUID) -> list[Any]:
    """Read insertion_chunks rows for one document straight from the database."""
    from app.registry import InsertionChunk

    stmt = select(InsertionChunk).where(InsertionChunk.doc_id == doc_id)
    return list(session.scalars(stmt).all())


DOC_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
EP_1 = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
EP_2 = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
EP_3 = uuid.UUID("00000000-0000-0000-0000-0000000000e3")


async def test_recovery_removes_all_tracked_episodes_and_marks_interrupted(
    recovery_module: ModuleType, session_factory: sessionmaker[Session]
) -> None:
    from app.registry import Document, mark_chunk_inserted

    with session_factory() as session:
        _make_document(session, DOC_ID)
        _track(session, DOC_ID, EP_1, 0)
        _track(session, DOC_ID, EP_2, 1)
        _track(session, DOC_ID, EP_3, 2)
        mark_chunk_inserted(session, EP_2)
        mark_chunk_inserted(session, EP_3)

    fake_graph = FakeGraphService()
    recovered = await recovery_module.run_startup_recovery(fake_graph)

    assert recovered == 1
    assert fake_graph.remove_calls == [str(EP_1), str(EP_2), str(EP_3)]

    with session_factory() as session:
        assert _chunk_rows(session, DOC_ID) == []
        doc = session.get(Document, DOC_ID)
        assert doc is not None, "the document row must stay so the owner can delete it"
        assert doc.status == "interrupted"
        assert doc.error == recovery_module.INTERRUPTED_MESSAGE


async def test_second_recovery_run_does_nothing(
    recovery_module: ModuleType, session_factory: sessionmaker[Session]
) -> None:
    from app.registry import Document

    with session_factory() as session:
        _make_document(session, DOC_ID)
        _track(session, DOC_ID, EP_1, 0)
        _track(session, DOC_ID, EP_2, 1)

    first_graph = FakeGraphService()
    assert await recovery_module.run_startup_recovery(first_graph) == 1
    assert len(first_graph.remove_calls) == 2

    second_graph = FakeGraphService()
    assert await recovery_module.run_startup_recovery(second_graph) == 0
    assert second_graph.remove_calls == []

    with session_factory() as session:
        assert _chunk_rows(session, DOC_ID) == []
        doc = session.get(Document, DOC_ID)
        assert doc is not None
        assert doc.status == "interrupted"
        assert doc.error == recovery_module.INTERRUPTED_MESSAGE


async def test_recovery_skips_missing_episode_and_still_cleans_up(
    recovery_module: ModuleType, session_factory: sessionmaker[Session]
) -> None:
    from app.registry import Document

    with session_factory() as session:
        _make_document(session, DOC_ID)
        _track(session, DOC_ID, EP_1, 0)

    fake_graph = FakeGraphService()
    assert fake_graph.episodes == {}, "the fake must not know this episode, so it is missing"

    recovered = await recovery_module.run_startup_recovery(fake_graph)

    assert recovered == 1
    assert fake_graph.remove_calls == [str(EP_1)]
    assert fake_graph.episodes == {}

    with session_factory() as session:
        assert _chunk_rows(session, DOC_ID) == []
        doc = session.get(Document, DOC_ID)
        assert doc is not None
        assert doc.status == "interrupted"


async def test_recovery_touches_only_processing_documents(
    recovery_module: ModuleType, session_factory: sessionmaker[Session]
) -> None:
    from app.registry import Document

    doc_a = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
    doc_b = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
    doc_done = uuid.UUID("00000000-0000-0000-0000-0000000000c1")

    with session_factory() as session:
        _make_document(session, doc_a)
        _track(session, doc_a, EP_1, 0)
        _make_document(session, doc_b)
        _track(session, doc_b, EP_2, 0)
        _track(session, doc_b, EP_3, 1)
        _make_document(session, doc_done, status_after="done")

    fake_graph = FakeGraphService()
    recovered = await recovery_module.run_startup_recovery(fake_graph)

    assert recovered == 2
    assert len(fake_graph.remove_calls) == 3
    assert sorted(fake_graph.remove_calls) == sorted([str(EP_1), str(EP_2), str(EP_3)])

    with session_factory() as session:
        for processing_id in (doc_a, doc_b):
            doc = session.get(Document, processing_id)
            assert doc is not None
            assert doc.status == "interrupted"
            assert doc.error == recovery_module.INTERRUPTED_MESSAGE
            assert _chunk_rows(session, processing_id) == []

        done = session.get(Document, doc_done)
        assert done is not None
        assert done.status == "done"
        assert done.error is None
        assert _chunk_rows(session, doc_done) == []
