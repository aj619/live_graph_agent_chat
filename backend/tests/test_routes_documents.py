"""Tests for the document routes: GET, POST and DELETE /api/documents (plan §6.1, §6.3, §6.5).

Only `app.routes_documents.router` is mounted, on a scratch FastAPI app built inside
this file. main.py is never imported, and no lifespan runs. The route's graph and bus
dependencies are overridden through `app.dependency_overrides`. The graph is
`tests.fakes.FakeGraphService`, so no Neo4j or LLM call is made. The background
`insert_document` task that POST schedules runs for real against the fake graph,
and TestClient runs it before the response returns.

Three modules each bind their own `SessionLocal` name, so all three are redirected to
one in-memory SQLite engine: `app.routes_documents`, `app.insert` (background task),
and `app.recovery` (DELETE). No MySQL connection is made. Settings come from a
placeholder `.env.test` in tmp_path. DATA_DIR points at tmp_path, so nothing is
written into the repository.
"""

import asyncio
import importlib
import json
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fakes import FakeGraphService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

TEST_TOKEN = "test-token-abc-123"
WRONG_TOKEN = "wrong-token-xyz-999"
TOKEN_HEADER = "X-API-Token"
AUTH = {TOKEN_HEADER: TEST_TOKEN}
EVENT_DOCUMENT_STATUS = "document.status"

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

TXT_BODY = (
    "The quarterly report covers revenue.\n\n"
    "Costs fell in the second quarter.\n\n"
    "Hiring continues into the third quarter.\n"
)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """Build the scratch app with the documents router, against a placeholder config."""
    env_text = "\n".join(f"{key}={value}" for key, value in ENV_VALUES.items()) + "\n"
    (tmp_path / ".env.test").write_text(env_text, encoding="utf-8")

    environ = dict(os.environ)
    environ["APP_ENV"] = "test"
    monkeypatch.setattr(os, "environ", environ)

    # Run app/config.py with its final load line removed, under a fake __file__, so the
    # env file lookup resolves to tmp_path and never to the real repo env files.
    source = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "\nsettings = load_settings()\n"
    assert source.count(marker) == 1, "app/config.py must end with one module-level load_settings()"
    source = source.replace(marker, "\n")
    config = ModuleType("app.config")
    config.__file__ = str(tmp_path / "backend" / "app" / "config.py")
    exec(compile(source, config.__file__, "exec"), config.__dict__)
    config.__dict__["settings"] = config.__dict__["load_settings"]()

    # Every app module that reads app.config at import time is re-imported against the
    # placeholder config. monkeypatch restores the originals after the test.
    app_package = importlib.import_module("app")
    monkeypatch.setitem(sys.modules, "app.config", config)
    monkeypatch.setattr(app_package, "config", config, raising=False)
    for name in list(sys.modules):
        if name.startswith("app.") and name != "app.config":
            monkeypatch.delitem(sys.modules, name, raising=False)

    settings = config.settings
    monkeypatch.setattr(settings, "API_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(settings, "ALLOWED_EXTENSIONS", "pdf,docx,txt")
    monkeypatch.setattr(settings, "MAX_DOCUMENTS", 10)
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 5)
    monkeypatch.setattr(settings, "INGEST_CHUNK_CHARS", 1000)
    monkeypatch.setattr(settings, "INGEST_RETRIES", 2)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))

    db_module = importlib.import_module("app.db")
    registry = importlib.import_module("app.registry")
    insert_module = importlib.import_module("app.insert")
    recovery_module = importlib.import_module("app.recovery")
    routes_documents = importlib.import_module("app.routes_documents")
    events = importlib.import_module("app.events")

    # One in-memory SQLite database shared by all three modules that bind SessionLocal.
    # StaticPool keeps one connection, so every session sees the same tables and rows.
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    db_module.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(routes_documents, "SessionLocal", factory)
    monkeypatch.setattr(insert_module, "SessionLocal", factory)
    monkeypatch.setattr(recovery_module, "SessionLocal", factory)

    fake_graph = FakeGraphService()
    bus = events.EventBus()

    app = FastAPI()
    app.include_router(routes_documents.router)
    app.dependency_overrides[routes_documents.get_graph_service] = lambda: fake_graph
    app.dependency_overrides[routes_documents.get_event_bus] = lambda: bus

    data_dir = tmp_path / "data"
    yield SimpleNamespace(
        app=app,
        routes_documents=routes_documents,
        registry=registry,
        insert=insert_module,
        recovery=recovery_module,
        settings=settings,
        factory=factory,
        fake_graph=fake_graph,
        bus=bus,
        uploads_dir=data_dir / "uploads",
    )
    engine.dispose()

    for name in list(sys.modules):
        if name.startswith("app.") and name != "app.config":
            sys.modules.pop(name, None)


@pytest.fixture
def client(env: SimpleNamespace) -> TestClient:
    """A TestClient over the scratch app."""
    return TestClient(env.app)


def _upload_files(env: SimpleNamespace) -> list[str]:
    """Names of every file in the uploads directory, or [] when the directory was never made."""
    if not env.uploads_dir.exists():
        return []
    return sorted(path.name for path in env.uploads_dir.iterdir())


def _document_rows(env: SimpleNamespace) -> list[Any]:
    """Every documents row, read through a fresh session."""
    with env.factory() as session:
        return list(env.registry.list_documents(session))


def _chunk_rows(env: SimpleNamespace, doc_id: uuid.UUID) -> list[Any]:
    """Every insertion_chunks row of one document, in chunk order."""
    with env.factory() as session:
        return list(env.registry.list_tracked_chunks(session, doc_id))


def _create_row(
    env: SimpleNamespace,
    *,
    filename: str = "existing.txt",
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a documents row directly through the registry, as an earlier upload would."""
    doc_id = uuid.uuid4()
    with env.factory() as session:
        env.registry.create_document(
            session,
            doc_id=doc_id,
            filename=filename,
            stored_name=f"{doc_id}.txt",
            size_bytes=3,
        )
        if created_at is not None:
            row = session.get(env.registry.Document, doc_id)
            assert row is not None
            row.created_at = created_at
            session.commit()
    return doc_id


def _upload(
    client: TestClient,
    filename: str,
    content: bytes,
    headers: dict[str, str] | None = None,
) -> Any:
    """POST one multipart upload to /api/documents."""
    return client.post(
        "/api/documents",
        files={"file": (filename, content, "text/plain")},
        headers=AUTH if headers is None else headers,
    )


def _status_events(queue: asyncio.Queue[str | None]) -> list[dict[str, Any]]:
    """Drain a bus subscriber queue and return the data of each document.status block."""
    events: list[dict[str, Any]] = []
    while True:
        try:
            block = queue.get_nowait()
        except asyncio.QueueEmpty:
            return events
        assert block is not None
        lines = block.strip().split("\n")
        if lines[0] == f"event: {EVENT_DOCUMENT_STATUS}":
            events.append(json.loads(lines[1].removeprefix("data: ")))


# --- GET /api/documents --------------------------------------------------------


def test_list_documents_rejects_missing_or_wrong_token(client: TestClient) -> None:
    """GET /api/documents returns 401 with no token and with a wrong token."""
    missing = client.get("/api/documents")
    wrong = client.get("/api/documents", headers={TOKEN_HEADER: WRONG_TOKEN})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid API token."


def test_list_documents_returns_empty_list_when_none_exist(client: TestClient) -> None:
    """GET /api/documents with the token returns 200 and an empty documents list."""
    response = client.get("/api/documents", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_list_documents_returns_rows_newest_first_with_public_fields(
    env: SimpleNamespace, client: TestClient
) -> None:
    """GET /api/documents lists each row newest first, with exactly the public fields."""
    older_id = _create_row(env, filename="older.txt", created_at=datetime(2026, 1, 1, 9, 0, 0))
    newer_id = _create_row(env, filename="newer.txt", created_at=datetime(2026, 2, 1, 9, 0, 0))

    response = client.get("/api/documents", headers=AUTH)

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [doc["id"] for doc in documents] == [str(newer_id), str(older_id)]
    assert set(documents[0]) == {
        "id",
        "filename",
        "status",
        "error",
        "chunks_total",
        "chunks_done",
        "created_at",
    }
    assert documents[0] == {
        "id": str(newer_id),
        "filename": "newer.txt",
        "status": "processing",
        "error": None,
        "chunks_total": None,
        "chunks_done": 0,
        "created_at": "2026-02-01T09:00:00",
    }
    assert datetime.fromisoformat(documents[1]["created_at"]) == datetime(2026, 1, 1, 9, 0, 0)


# --- POST /api/documents: token and validation order ---------------------------


def test_upload_rejects_missing_or_wrong_token_with_no_side_effect(
    env: SimpleNamespace, client: TestClient
) -> None:
    """POST /api/documents returns 401 for a missing or wrong token. No file or row is made."""
    missing = _upload(client, "notes.txt", TXT_BODY.encode(), headers={})
    wrong = _upload(client, "notes.txt", TXT_BODY.encode(), headers={TOKEN_HEADER: WRONG_TOKEN})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid API token."
    assert _upload_files(env) == []
    assert _document_rows(env) == []
    assert env.fake_graph.insert_calls == []


def test_upload_checks_token_before_document_limit(
    env: SimpleNamespace, client: TestClient
) -> None:
    """With the limit already reached, a request without a token gets 401, not 409."""
    env.settings.MAX_DOCUMENTS = 0

    response = _upload(client, "notes.txt", TXT_BODY.encode(), headers={})

    assert response.status_code == 401
    assert _upload_files(env) == []


def test_upload_rejects_with_409_when_max_documents_reached(
    env: SimpleNamespace, client: TestClient
) -> None:
    """POST returns 409 when MAX_DOCUMENTS is 0. No file is written and no row is created."""
    env.settings.MAX_DOCUMENTS = 0

    response = _upload(client, "notes.txt", TXT_BODY.encode())

    assert response.status_code == 409
    assert response.json()["detail"] == "The maximum number of documents has been reached."
    assert _upload_files(env) == []
    assert _document_rows(env) == []
    assert env.fake_graph.insert_calls == []


def test_upload_rejects_with_409_when_existing_count_equals_limit(
    env: SimpleNamespace, client: TestClient
) -> None:
    """With one stored document and MAX_DOCUMENTS at 1, a new upload gets 409 and the count is 1."""
    existing_id = _create_row(env)
    env.settings.MAX_DOCUMENTS = 1

    response = _upload(client, "notes.txt", TXT_BODY.encode())

    assert response.status_code == 409
    rows = _document_rows(env)
    assert [row.id for row in rows] == [existing_id]
    assert _upload_files(env) == []


def test_upload_checks_document_limit_before_extension(
    env: SimpleNamespace, client: TestClient
) -> None:
    """With the limit reached, a disallowed extension still gets 409. The count is checked first."""
    env.settings.MAX_DOCUMENTS = 0

    response = _upload(client, "malware.exe", b"MZ-not-a-document")

    assert response.status_code == 409
    assert _upload_files(env) == []


@pytest.mark.parametrize("filename", ["malware.exe", "archive.zip", "noextension"])
def test_upload_rejects_disallowed_extension_with_415(
    env: SimpleNamespace, client: TestClient, filename: str
) -> None:
    """POST returns 415 for an extension outside ALLOWED_EXTENSIONS, or for no extension."""
    response = _upload(client, filename, b"some bytes")

    assert response.status_code == 415
    assert response.json()["detail"] == "This file type is not allowed."
    assert _upload_files(env) == []
    assert _document_rows(env) == []
    assert env.fake_graph.insert_calls == []


def test_upload_checks_extension_before_size(env: SimpleNamespace, client: TestClient) -> None:
    """An oversized file with a disallowed extension gets 415, so the extension is checked first."""
    env.settings.MAX_FILE_SIZE_MB = 0

    response = _upload(client, "malware.exe", b"x")

    assert response.status_code == 415


def test_upload_rejects_oversized_file_with_413(env: SimpleNamespace, client: TestClient) -> None:
    """POST returns 413 when the file is larger than MAX_FILE_SIZE_MB. Nothing is stored."""
    env.settings.MAX_FILE_SIZE_MB = 0

    response = _upload(client, "notes.txt", b"x")

    assert response.status_code == 413
    assert response.json()["detail"] == "The file is larger than the allowed size."
    assert _upload_files(env) == []
    assert _document_rows(env) == []
    assert env.fake_graph.insert_calls == []


def test_upload_accepts_uppercase_allowed_extension_and_stores_lowercase(
    env: SimpleNamespace, client: TestClient
) -> None:
    """NOTES.TXT is allowed (the check is case-insensitive) and is stored as <id>.txt."""
    response = _upload(client, "NOTES.TXT", TXT_BODY.encode())

    assert response.status_code == 201
    doc_id = response.json()["id"]
    assert _upload_files(env) == [f"{doc_id}.txt"]


# --- POST /api/documents: success and failure paths ----------------------------


def test_upload_success_returns_201_stores_file_and_runs_full_pipeline(
    env: SimpleNamespace, client: TestClient
) -> None:
    """A valid .txt upload returns 201, stores the file, and the background insert finishes."""
    queue = env.bus.subscribe()
    content = TXT_BODY.encode("utf-8")

    response = _upload(client, "notes.txt", content)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "filename",
        "status",
        "error",
        "chunks_total",
        "chunks_done",
        "created_at",
    }
    assert body["filename"] == "notes.txt"
    # The response is built before the background task runs, so it reports processing.
    assert body["status"] == "processing"
    assert body["error"] is None
    doc_id = uuid.UUID(body["id"])

    stored = env.uploads_dir / f"{doc_id}.txt"
    assert stored.read_bytes() == content
    assert _upload_files(env) == [f"{doc_id}.txt"]

    # TestClient has already run the background insert. Read the row back to see its final state.
    rows = _document_rows(env)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == doc_id
    assert row.filename == "notes.txt"
    assert row.stored_name == f"{doc_id}.txt"
    assert row.size_bytes == len(content)
    assert row.status == "done"
    assert row.error is None

    chunks = _chunk_rows(env, doc_id)
    assert len(chunks) >= 1
    assert all(chunk.state == "inserted" for chunk in chunks)
    assert row.chunks_total == len(chunks)
    assert row.chunks_done == len(chunks)

    assert len(env.fake_graph.insert_calls) == len(chunks)
    assert env.fake_graph.insert_calls[0]["source_description"] == "notes.txt"

    events = _status_events(queue)
    assert events[0] == {
        "id": str(doc_id),
        "status": "processing",
        "error": None,
        "chunks_done": 0,
        "chunks_total": None,
    }
    assert events[-1]["id"] == str(doc_id)
    assert events[-1]["status"] == "done"
    assert events[-1]["chunks_done"] == len(chunks)
    env.bus.unsubscribe(queue)


def test_upload_empty_file_is_accepted_then_marked_failed_in_background(
    env: SimpleNamespace, client: TestClient
) -> None:
    """An empty file passes the size check, gets 201, and then fails in the background task."""
    env.settings.MAX_FILE_SIZE_MB = 0

    response = _upload(client, "notes.txt", b"")

    assert response.status_code == 201
    doc_id = uuid.UUID(response.json()["id"])
    rows = _document_rows(env)
    assert len(rows) == 1
    assert rows[0].id == doc_id
    assert rows[0].status == "failed"
    assert rows[0].error is not None
    assert _chunk_rows(env, doc_id) == []
    assert env.fake_graph.insert_calls == []


def test_upload_removes_stored_file_when_row_creation_fails(
    env: SimpleNamespace, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If creating the row raises, the just-written file is deleted and the error re-raised."""

    def _fail_create(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(env.routes_documents, "create_document", _fail_create)

    with pytest.raises(RuntimeError, match="simulated registry failure"):
        _upload(client, "notes.txt", TXT_BODY.encode())

    assert _upload_files(env) == []
    assert _document_rows(env) == []
    assert env.fake_graph.insert_calls == []


# --- DELETE /api/documents/{doc_id} --------------------------------------------


def test_delete_rejects_missing_or_wrong_token_and_touches_nothing(
    env: SimpleNamespace, client: TestClient
) -> None:
    """DELETE returns 401 with no token or a wrong one. The row, file and graph are untouched."""
    doc_id = _create_row(env)
    stored = env.uploads_dir / f"{doc_id}.txt"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"abc")

    missing = client.delete(f"/api/documents/{doc_id}")
    wrong = client.delete(f"/api/documents/{doc_id}", headers={TOKEN_HEADER: WRONG_TOKEN})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert [row.id for row in _document_rows(env)] == [doc_id]
    assert stored.read_bytes() == b"abc"
    assert env.fake_graph.remove_calls == []


def test_delete_unknown_document_returns_404(env: SimpleNamespace, client: TestClient) -> None:
    """DELETE returns 404 for a well-formed id that was never created, and removes nothing."""
    unknown = uuid.uuid4()

    response = client.delete(f"/api/documents/{unknown}", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."
    assert env.fake_graph.remove_calls == []


def test_delete_malformed_id_returns_422(env: SimpleNamespace, client: TestClient) -> None:
    """DELETE returns 422 when the path id is not a UUID, and the graph is never called."""
    response = client.delete("/api/documents/not-a-uuid", headers=AUTH)

    assert response.status_code == 422
    assert env.fake_graph.remove_calls == []


def test_delete_existing_document_returns_204_and_removes_row_chunks_file_and_episodes(
    env: SimpleNamespace, client: TestClient
) -> None:
    """DELETE returns 204 after a full upload. Row, chunks, file and episodes are all removed."""
    upload = _upload(client, "notes.txt", TXT_BODY.encode())
    assert upload.status_code == 201
    doc_id = uuid.UUID(upload.json()["id"])

    chunks_before = _chunk_rows(env, doc_id)
    episode_ids = [str(chunk.episode_uuid) for chunk in chunks_before]
    assert len(episode_ids) >= 1
    stored = env.uploads_dir / f"{doc_id}.txt"
    assert stored.exists()

    response = client.delete(f"/api/documents/{doc_id}", headers=AUTH)

    assert response.status_code == 204
    assert response.content == b""
    assert _document_rows(env) == []
    assert _chunk_rows(env, doc_id) == []
    assert not stored.exists()
    assert _upload_files(env) == []
    assert env.fake_graph.remove_calls == episode_ids
    assert env.fake_graph.episodes == {}


def test_delete_same_document_twice_returns_404_the_second_time(
    env: SimpleNamespace, client: TestClient
) -> None:
    """After a successful DELETE, a second DELETE of the same id returns 404."""
    doc_id = _create_row(env)

    first = client.delete(f"/api/documents/{doc_id}", headers=AUTH)
    second = client.delete(f"/api/documents/{doc_id}", headers=AUTH)

    assert first.status_code == 204
    assert second.status_code == 404
    assert _document_rows(env) == []
