"""Tests for the background insertion service in app.insert (plan §6.5, steps 2 to 6).

These are unit tests. They need no MySQL, no Neo4j, and no LLM endpoint.

app.db builds its engine against MySQL at import time, and app.insert binds
SessionLocal from app.db into its own namespace. So each test:

- builds a placeholder app.config from source under a fake __file__ in tmp_path,
  with a minimal .env.test there (the same pattern as tests/test_logging.py), so
  the real repo env files are never read;
- imports app.db, app.registry and app.insert against that config;
- replaces app.insert.SessionLocal with a session factory bound to an in-memory
  SQLite engine, whose tables come from the real registry models.

Chunk sizes and retry counts are set per test on the one settings object. The
graph is tests.fakes.FakeGraphService, or a small subclass that always fails.
Database rows are read back from SQLite, and the bus events are read from a
subscriber queue.
"""

import importlib
import json
import os
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fakes import FakeFailure, FakeGraphService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.events import EventBus

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"
PACKAGE_MODULES = ("app.config", "app.db", "app.registry", "app.insert")

# Placeholder values for every required field in plan §5. None is a real secret.
ENV_VALUES: dict[str, Any] = {
    "APP_ENV": "test",
    "API_TOKEN": "placeholder-api-token",
    "CORS_ORIGINS": "http://localhost:5173",
    "MAX_DOCUMENTS": 10,
    "MAX_FILE_SIZE_MB": 5,
    "ALLOWED_EXTENSIONS": "pdf,docx,txt",
    "INGEST_CHUNK_CHARS": 1000,
    "INGEST_RETRIES": 2,
    "AGENT_MAX_REWRITES": 2,
    "AGENT_QUERY_EXPANSIONS": 2,
    "RETRIEVAL_LIMIT": 5,
    "GRAPH_SNAPSHOT_LIMIT": 100,
    "GRAPH_GROUP_ID": "test_group",
    "DATA_DIR": "./data",
    "MYSQL_HOST": "mysql",
    "MYSQL_PORT": 3306,
    "MYSQL_DATABASE": "placeholder_db_test",
    "MYSQL_USER": "placeholder_user",
    "MYSQL_PASSWORD": "placeholder-mysql-password",
    "MYSQL_ROOT_PASSWORD": "placeholder-mysql-root-password",
    "NEO4J_URI": "bolt://neo4j:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "placeholder-neo4j-password",
    "NEO4J_DATABASE": "neo4j_test",
    "LLM_BASE_URL": "http://llm.invalid/v1",
    "LLM_API_KEY": "placeholder-llm-key",
    "LLM_MODEL": "placeholder-model",
    "LLM_SMALL_MODEL": "placeholder-small-model",
    "LLM_TEMPERATURE": 0.0,
    "EMBEDDING_BASE_URL": "http://embed.invalid/v1",
    "EMBEDDING_API_KEY": "placeholder-embedding-key",
    "EMBEDDING_MODEL": "placeholder-embedding-model",
    "RERANKER_ENABLED": False,
    "RERANKER_BASE_URL": "http://rerank.invalid/v1",
    "RERANKER_API_KEY": "placeholder-rerank-key",
    "RERANKER_MODEL": "placeholder-rerank-model",
    "AGENT_LLM_BASE_URL": "http://agent.invalid/v1",
    "AGENT_LLM_API_KEY": "placeholder-agent-key",
    "AGENT_LLM_MODEL": "placeholder-agent-model",
    "AGENT_LLM_TEMPERATURE": 0.5,
    "LANGFUSE_ENABLED": False,
    "LANGFUSE_HOST": "http://langfuse.invalid",
    "LANGFUSE_PUBLIC_KEY": "placeholder-public-key",
    "LANGFUSE_SECRET_KEY": "placeholder-secret-key",
    "NEXTAUTH_SECRET": "placeholder-nextauth-secret",
    "NEXTAUTH_URL": "http://localhost:3000",
    "SALT": "placeholder-salt",
    "ENCRYPTION_KEY": "placeholder-encryption-key",
    "POSTGRES_USER": "placeholder_pg_user",
    "POSTGRES_PASSWORD": "placeholder-pg-password",
    "POSTGRES_DB": "placeholder_pg_db",
    "POSTGRES_VERSION": "17",
    "CLICKHOUSE_USER": "placeholder_ch_user",
    "CLICKHOUSE_PASSWORD": "placeholder-ch-password",
    "REDIS_AUTH": "placeholder-redis-auth",
    "MINIO_ROOT_USER": "placeholder_minio_user",
    "MINIO_ROOT_PASSWORD": "placeholder-minio-password",
}

# Chunk limit of 10 characters. Each paragraph below is exactly 10 characters,
# so every paragraph becomes one chunk, and the chunk count equals the paragraph count.
CHUNK_LIMIT = 10


@dataclass
class InsertEnv:
    """The modules and the one settings object a test works with."""

    config: ModuleType
    db: ModuleType
    registry: ModuleType
    insert: ModuleType
    settings: Any


@pytest.fixture
def insert_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[InsertEnv]:
    """Import app.config from placeholder source, then app.db, app.registry and app.insert."""
    env_text = "\n".join(f"{key}={value}" for key, value in ENV_VALUES.items()) + "\n"
    (tmp_path / ".env.test").write_text(env_text, encoding="utf-8")

    env = dict(os.environ)
    env["APP_ENV"] = "test"
    monkeypatch.setattr(os, "environ", env)

    # Run app/config.py without its final load line, under a fake __file__, so
    # REPO_ROOT resolves to tmp_path and the real repo env files are never read.
    source = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "\nsettings = load_settings()\n"
    assert source.count(marker) == 1, "app/config.py must end with one module-level load_settings()"
    source = source.replace(marker, "\n")
    config = ModuleType("app.config")
    config.__file__ = str(tmp_path / "backend" / "app" / "config.py")
    exec(compile(source, config.__file__, "exec"), config.__dict__)
    config.__dict__["settings"] = config.__dict__["load_settings"]()

    app_package = importlib.import_module("app")
    for name in PACKAGE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "app.config", config)
    monkeypatch.setattr(app_package, "config", config, raising=False)
    db_module = importlib.import_module("app.db")
    registry_module = importlib.import_module("app.registry")
    insert_module = importlib.import_module("app.insert")

    monkeypatch.setattr(config.settings, "INGEST_CHUNK_CHARS", CHUNK_LIMIT)
    monkeypatch.setattr(config.settings, "INGEST_RETRIES", 3)

    yield InsertEnv(
        config=config,
        db=db_module,
        registry=registry_module,
        insert=insert_module,
        settings=config.settings,
    )

    # Drop the modules built against the placeholder config so no other test sees them.
    for name in PACKAGE_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def sqlite_factory(insert_env: InsertEnv, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Give app.insert a fresh in-memory SQLite session factory with the registry tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    insert_env.db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(insert_env.insert, "SessionLocal", factory)
    yield factory
    engine.dispose()


class _AlwaysFailingGraph(FakeGraphService):
    """A graph whose every insert_episode attempt raises FakeFailure, and which counts them."""

    async def insert_episode(
        self,
        episode_uuid: str,
        name: str,
        body: str,
        source_description: str,
    ) -> None:
        self.insert_calls.append(
            {
                "episode_uuid": episode_uuid,
                "name": name,
                "body": body,
                "source_description": source_description,
            }
        )
        self.call_counts["insert_episode"] = self.call_counts.get("insert_episode", 0) + 1
        raise FakeFailure(f"always-failing insert on attempt {self.call_counts['insert_episode']}")


def _seed_document(
    insert_env: InsertEnv,
    factory: Any,
    tmp_path: Path,
    content: bytes,
) -> tuple[uuid.UUID, Path]:
    """Write the saved file and create its documents row with status processing."""
    doc_id = uuid.uuid4()
    file_path = tmp_path / f"{doc_id}.txt"
    file_path.write_bytes(content)
    with factory() as session:
        insert_env.registry.create_document(
            session,
            doc_id=doc_id,
            filename="doc.txt",
            stored_name=file_path.name,
            size_bytes=len(content),
        )
    return doc_id, file_path


def _read_document(insert_env: InsertEnv, factory: Any, doc_id: uuid.UUID) -> dict[str, Any]:
    """Return the document row's fields, read back from SQLite in a fresh session."""
    with factory() as session:
        doc = session.get(insert_env.registry.Document, doc_id)
        assert doc is not None
        return {
            "status": doc.status,
            "error": doc.error,
            "chunks_total": doc.chunks_total,
            "chunks_done": doc.chunks_done,
        }


def _read_chunks(insert_env: InsertEnv, factory: Any, doc_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return the insertion_chunks rows for one document, in chunk order, from SQLite."""
    with factory() as session:
        rows = insert_env.registry.list_tracked_chunks(session, doc_id)
        return [
            {
                "chunk_index": row.chunk_index,
                "state": row.state,
                "episode_uuid": str(row.episode_uuid),
            }
            for row in rows
        ]


def _drain(queue: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return every (event type, data) pair queued on a bus subscriber, in publish order."""
    events: list[tuple[str, dict[str, Any]]] = []
    while not queue.empty():
        block: str = queue.get_nowait()
        event_line, data_line = block.strip().split("\n")
        events.append(
            (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        )
    return events


async def test_insert_success_marks_every_chunk_inserted_and_document_done(
    insert_env: InsertEnv, sqlite_factory: Any, tmp_path: Path
) -> None:

    text = "aaaaaaaaaa\n\nbbbbbbbbbb\n\ncccccccccc"
    doc_id, file_path = _seed_document(insert_env, sqlite_factory, tmp_path, text.encode("utf-8"))
    graph = FakeGraphService()
    bus = EventBus()
    queue = bus.subscribe()

    await insert_env.insert.insert_document(doc_id, file_path, "txt", "doc.txt", graph, bus)

    document = _read_document(insert_env, sqlite_factory, doc_id)
    assert document == {
        "status": "done",
        "error": None,
        "chunks_total": 3,
        "chunks_done": 3,
    }

    chunks = _read_chunks(insert_env, sqlite_factory, doc_id)
    assert [(row["chunk_index"], row["state"]) for row in chunks] == [
        (0, "inserted"),
        (1, "inserted"),
        (2, "inserted"),
    ]

    assert len(graph.insert_calls) == 3
    attempted_uuids = [call["episode_uuid"] for call in graph.insert_calls]
    assert len(set(attempted_uuids)) == 3
    assert attempted_uuids == [row["episode_uuid"] for row in chunks]
    assert [call["body"] for call in graph.insert_calls] == [
        "aaaaaaaaaa",
        "bbbbbbbbbb",
        "cccccccccc",
    ]
    assert [call["name"] for call in graph.insert_calls] == [
        "chunk 1 of 3",
        "chunk 2 of 3",
        "chunk 3 of 3",
    ]
    assert len(graph.episodes) == 3

    events = _drain(queue)
    status_events = [data for kind, data in events if kind == "document.status"]
    assert status_events[-1]["status"] == "done"
    assert status_events[-1]["chunks_done"] == 3
    assert status_events[-1]["chunks_total"] == 3
    assert status_events[-1]["id"] == str(doc_id)
    graph_events = [data for kind, data in events if kind == "graph.changed"]
    assert graph_events == [{"doc_id": str(doc_id)}]
    assert events[-1][0] == "graph.changed"


async def test_insert_failure_on_chunk_3_of_5_keeps_chunks_1_and_2_tracked(
    insert_env: InsertEnv, sqlite_factory: Any, tmp_path: Path
) -> None:

    insert_env.settings.INGEST_RETRIES = 1
    text = "\n\n".join(["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc", "dddddddddd", "eeeeeeeeee"])
    doc_id, file_path = _seed_document(insert_env, sqlite_factory, tmp_path, text.encode("utf-8"))
    graph = FakeGraphService(fail_on={"insert_episode": 3})
    bus = EventBus()
    queue = bus.subscribe()

    await insert_env.insert.insert_document(doc_id, file_path, "txt", "doc.txt", graph, bus)

    document = _read_document(insert_env, sqlite_factory, doc_id)
    assert document["status"] == "failed"
    assert document["chunks_total"] == 5
    assert document["chunks_done"] == 2
    assert document["error"] == ("insertion failed on chunk 3 of 5 (FakeFailure)")

    chunks = _read_chunks(insert_env, sqlite_factory, doc_id)
    assert [(row["chunk_index"], row["state"]) for row in chunks] == [
        (0, "inserted"),
        (1, "inserted"),
        (2, "pending"),
    ]

    assert len(graph.insert_calls) == 3
    assert [call["body"] for call in graph.insert_calls] == [
        "aaaaaaaaaa",
        "bbbbbbbbbb",
        "cccccccccc",
    ]

    events = _drain(queue)
    status_events = [data for kind, data in events if kind == "document.status"]
    assert status_events[-1]["status"] == "failed"
    assert status_events[-1]["error"] == document["error"]
    assert not [kind for kind, _ in events if kind == "graph.changed"]


async def test_unsupported_document_fails_at_once_without_retry_or_chunks(
    insert_env: InsertEnv, sqlite_factory: Any, tmp_path: Path
) -> None:

    insert_env.settings.INGEST_RETRIES = 3
    # Whitespace only: extract_text raises UnsupportedDocument before any chunking.
    doc_id, file_path = _seed_document(insert_env, sqlite_factory, tmp_path, b"   \n\n  \n")
    graph = FakeGraphService()
    bus = EventBus()
    queue = bus.subscribe()

    await insert_env.insert.insert_document(doc_id, file_path, "txt", "doc.txt", graph, bus)

    document = _read_document(insert_env, sqlite_factory, doc_id)
    assert document["status"] == "failed"
    assert document["error"] == "no text could be extracted from the txt document"
    assert document["chunks_total"] is None
    assert _read_chunks(insert_env, sqlite_factory, doc_id) == []
    assert graph.call_counts == {}
    assert graph.insert_calls == []

    events = _drain(queue)
    status_events = [data for kind, data in events if kind == "document.status"]
    assert len(status_events) == 1
    assert status_events[0]["status"] == "failed"


async def test_missing_file_fails_as_unreadable_without_retry(
    insert_env: InsertEnv, sqlite_factory: Any, tmp_path: Path
) -> None:

    doc_id = uuid.uuid4()
    with sqlite_factory() as session:
        insert_env.registry.create_document(
            session,
            doc_id=doc_id,
            filename="doc.txt",
            stored_name="missing.txt",
            size_bytes=0,
        )
    graph = FakeGraphService()
    bus = EventBus()

    await insert_env.insert.insert_document(
        doc_id, tmp_path / "missing.txt", "txt", "doc.txt", graph, bus
    )

    document = _read_document(insert_env, sqlite_factory, doc_id)
    assert document["status"] == "failed"
    assert document["error"] == "document could not be read (FileNotFoundError)"
    assert _read_chunks(insert_env, sqlite_factory, doc_id) == []
    assert graph.call_counts == {}


async def test_insert_stops_after_ingest_retries_attempts_on_one_chunk(
    insert_env: InsertEnv, sqlite_factory: Any, tmp_path: Path
) -> None:

    insert_env.settings.INGEST_RETRIES = 3
    insert_env.settings.INGEST_CHUNK_CHARS = 1000
    doc_id, file_path = _seed_document(insert_env, sqlite_factory, tmp_path, b"hello")
    graph = _AlwaysFailingGraph()
    bus = EventBus()
    queue = bus.subscribe()

    await insert_env.insert.insert_document(doc_id, file_path, "txt", "doc.txt", graph, bus)

    assert graph.call_counts["insert_episode"] == 3
    assert len(graph.insert_calls) == 3
    attempted_uuids = {call["episode_uuid"] for call in graph.insert_calls}
    assert len(attempted_uuids) == 1, "every retry reuses the chunk's episode UUID"

    document = _read_document(insert_env, sqlite_factory, doc_id)
    assert document["status"] == "failed"
    assert document["error"] == "insertion failed on chunk 1 of 1 (FakeFailure)"
    assert document["chunks_done"] == 0

    chunks = _read_chunks(insert_env, sqlite_factory, doc_id)
    assert [(row["chunk_index"], row["state"]) for row in chunks] == [(0, "pending")]
    assert chunks[0]["episode_uuid"] in attempted_uuids

    events = _drain(queue)
    status_events = [data for kind, data in events if kind == "document.status"]
    assert status_events[-1]["status"] == "failed"
    assert not [kind for kind, _ in events if kind == "graph.changed"]
