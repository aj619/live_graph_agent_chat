"""Tests for the document deletion path (plan §6.5, app.recovery.delete_document_everywhere).

delete_document_everywhere opens sessions through `SessionLocal` from app.db, and
importing app.recovery needs an app.config that can load. These tests must not
read the real repo env files, so the fixture below puts a stub `app.config` into
sys.modules for the duration of the import only. The stub holds placeholder
values and never reads a file. The real MySQL engine is built lazily and never
connects. The tests then redirect `recovery_module.SessionLocal` to an in-memory
SQLite database, so every session runs against SQLite and no MySQL server is
touched. Each test gets a fresh engine and fresh tables.

The stored upload lives under `settings.DATA_DIR/uploads`. Each test points
DATA_DIR at a directory inside tmp_path and creates `uploads/` there, so the
file-deletion step acts on a real file and only under tmp_path.

No test here is marked `integration`. The tests need no live service.
"""

import importlib
import logging
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
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


@pytest.fixture
def data_dir(recovery_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point settings.DATA_DIR at a tmp_path directory and create its uploads/ subdirectory."""
    root = tmp_path / "data"
    (root / "uploads").mkdir(parents=True)
    monkeypatch.setattr(recovery_module.settings, "DATA_DIR", str(root))
    return root


def _create_document(session: Session, doc_id: uuid.UUID, stored_name: str) -> None:
    """Create one document row through the registry, with the given stored file name."""
    from app.registry import create_document

    create_document(
        session,
        doc_id=doc_id,
        filename="a.txt",
        stored_name=stored_name,
        size_bytes=10,
    )


def _track(session: Session, doc_id: uuid.UUID, episode: uuid.UUID, index: int) -> None:
    """Record one pending tracking row through the registry."""
    from app.registry import record_pending_chunk

    record_pending_chunk(session, episode_uuid=episode, doc_id=doc_id, chunk_index=index)


def _chunk_rows(session: Session, doc_id: uuid.UUID) -> list[Any]:
    """Read insertion_chunks rows for one document straight from the database."""
    from app.registry import InsertionChunk

    stmt = select(InsertionChunk).where(InsertionChunk.doc_id == doc_id)
    return list(session.scalars(stmt).all())


DOC_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
OTHER_DOC_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
EP_1 = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
EP_2 = uuid.UUID("00000000-0000-0000-0000-0000000000f2")
EP_3 = uuid.UUID("00000000-0000-0000-0000-0000000000f3")
STORED_NAME = "abc123.txt"


async def test_delete_removes_episodes_rows_and_stored_file(
    recovery_module: ModuleType,
    session_factory: sessionmaker[Session],
    data_dir: Path,
) -> None:
    from app.registry import Document, mark_chunk_inserted

    stored_path = data_dir / "uploads" / STORED_NAME
    stored_path.write_bytes(b"hello upload")

    with session_factory() as session:
        _create_document(session, DOC_ID, STORED_NAME)
        _track(session, DOC_ID, EP_1, 0)
        _track(session, DOC_ID, EP_2, 1)
        _track(session, DOC_ID, EP_3, 2)
        mark_chunk_inserted(session, EP_2)
    # A second document whose rows and episodes must be left alone.
    with session_factory() as session:
        _create_document(session, OTHER_DOC_ID, "other.txt")
        _track(session, OTHER_DOC_ID, uuid.UUID(int=0xABC), 0)

    fake_graph = FakeGraphService()
    for episode in (EP_1, EP_2, EP_3):
        fake_graph.episodes[str(episode)] = {"name": "n", "body": "b", "source_description": "s"}

    deleted = await recovery_module.delete_document_everywhere(fake_graph, DOC_ID)

    assert deleted is True
    assert sorted(fake_graph.remove_calls) == sorted([str(EP_1), str(EP_2), str(EP_3)])
    assert fake_graph.episodes == {}

    with session_factory() as session:
        assert session.get(Document, DOC_ID) is None, "the document row must be gone"
        assert _chunk_rows(session, DOC_ID) == [], "the insertion_chunks rows must be gone"
        other = session.get(Document, OTHER_DOC_ID)
        assert other is not None, "other documents must not be touched"
        assert len(_chunk_rows(session, OTHER_DOC_ID)) == 1

    assert not stored_path.exists(), "the stored upload file must be deleted"


async def test_delete_unknown_document_returns_false_and_touches_nothing(
    recovery_module: ModuleType,
    session_factory: sessionmaker[Session],
    data_dir: Path,
) -> None:
    from app.registry import Document

    kept_path = data_dir / "uploads" / STORED_NAME
    kept_path.write_bytes(b"unrelated upload")
    with session_factory() as session:
        _create_document(session, OTHER_DOC_ID, STORED_NAME)
        _track(session, OTHER_DOC_ID, EP_1, 0)

    fake_graph = FakeGraphService()
    missing_id = uuid.uuid4()

    deleted = await recovery_module.delete_document_everywhere(fake_graph, missing_id)

    assert deleted is False
    assert fake_graph.remove_calls == [], "no episode removal for a missing document"
    assert fake_graph.call_counts.get("remove_episode", 0) == 0
    assert kept_path.exists(), "an unrelated stored file must not be deleted"

    with session_factory() as session:
        assert session.get(Document, OTHER_DOC_ID) is not None
        assert len(_chunk_rows(session, OTHER_DOC_ID)) == 1


async def test_delete_with_missing_stored_file_still_succeeds_and_logs_warning(
    recovery_module: ModuleType,
    session_factory: sessionmaker[Session],
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.registry import Document

    stored_path = data_dir / "uploads" / STORED_NAME
    assert not stored_path.exists(), "precondition: the stored file is already missing"

    with session_factory() as session:
        _create_document(session, DOC_ID, STORED_NAME)
        _track(session, DOC_ID, EP_1, 0)
        _track(session, DOC_ID, EP_2, 1)

    fake_graph = FakeGraphService()
    with caplog.at_level(logging.WARNING, logger="app.recovery"):
        deleted = await recovery_module.delete_document_everywhere(fake_graph, DOC_ID)

    assert deleted is True
    assert sorted(fake_graph.remove_calls) == sorted([str(EP_1), str(EP_2)])
    assert any(
        record.levelno == logging.WARNING and "already missing" in record.getMessage()
        for record in caplog.records
    ), "a missing stored file must be logged as a warning"

    with session_factory() as session:
        assert session.get(Document, DOC_ID) is None
        assert _chunk_rows(session, DOC_ID) == []


async def test_delete_document_without_tracked_chunks_deletes_cleanly(
    recovery_module: ModuleType,
    session_factory: sessionmaker[Session],
    data_dir: Path,
) -> None:
    from app.registry import Document

    stored_path = data_dir / "uploads" / STORED_NAME
    stored_path.write_bytes(b"no chunks were ever tracked")

    with session_factory() as session:
        _create_document(session, DOC_ID, STORED_NAME)

    fake_graph = FakeGraphService()

    deleted = await recovery_module.delete_document_everywhere(fake_graph, DOC_ID)

    assert deleted is True
    assert fake_graph.remove_calls == [], "with no tracked chunks there is nothing to remove"
    assert fake_graph.call_counts.get("remove_episode", 0) == 0

    with session_factory() as session:
        assert session.get(Document, DOC_ID) is None
        assert _chunk_rows(session, DOC_ID) == []

    assert not stored_path.exists(), "the stored upload file must be deleted"
