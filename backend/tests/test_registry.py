"""Tests for the document and insertion-tracking registry against MySQL (plan §6.5, T2.T6).

Every test here is marked `integration`. It uses the real MySQL engine from
app.db, built from the MYSQL_* settings, and the real PyMySQL driver. It does
not use SQLite.

Settings: when the process APP_ENV is already `test`, the driver has set up the
test stack, so the real app.config is used as it is. The conftest guard checks
its values. Otherwise this module installs a placeholder `.env.test` in a temp
directory. It points MYSQL_HOST at 127.0.0.1:13306, where nothing listens in a
dev box, so the connection is refused at once. The module-scoped autouse
fixture below runs before conftest's function-scoped guard, so the guard sees
test-shaped settings. The real repo env files are never read, and the patched
modules and environment are restored when the module finishes.

Connectivity: each test first opens a real connection. If MySQL is not
reachable, the test skips with "not verified: MySQL not reachable". A skip is
reported as not verified, never as passed.

Cleanup: each test creates rows under fresh UUIDs and deletes them in teardown.
Nothing relies on the table being empty.
"""

import importlib
import os
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"
_PATCHED_MODULES = ("app.config", "app.db", "app.registry")

# Placeholder values for every required field in plan §5. None is a real secret.
# MYSQL_HOST and MYSQL_PORT point at a port with no listener, so a run without a
# test stack is refused quickly and skips as not verified.
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
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": 13306,
    "MYSQL_DATABASE": "registry_test",
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


def _build_test_config(env_dir: Path) -> ModuleType:
    """Build app.config from its source, with the module-level load removed.

    The caller points REPO_ROOT at env_dir and then calls load_settings(), so the
    only env file read is the placeholder .env.test in env_dir.
    """
    source = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "\nsettings = load_settings()\n"
    assert source.count(marker) == 1, "app/config.py must end with one module-level load_settings()"
    source = source.replace(marker, "\n")
    config = ModuleType("app.config")
    config.__file__ = str(CONFIG_PATH)
    exec(compile(source, str(CONFIG_PATH), "exec"), config.__dict__)
    config.__dict__["REPO_ROOT"] = env_dir
    config.__dict__["settings"] = config.__dict__["load_settings"]()
    return config


@pytest.fixture(scope="module", autouse=True)
def _registry_test_settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Install test-shaped settings for this module, before conftest's function-scoped guard.

    A module-scoped fixture is set up before any function-scoped fixture, so the
    conftest guard always sees the settings installed here.
    """
    if os.environ.get("APP_ENV") == "test":
        # The driver has set up the test stack. Use the real .env.test settings.
        yield
        return

    env_dir = tmp_path_factory.mktemp("registry_env")
    env_text = "\n".join(f"{key}={value}" for key, value in ENV_VALUES.items()) + "\n"
    (env_dir / ".env.test").write_text(env_text, encoding="utf-8")

    saved_environ = dict(os.environ)
    saved_modules = {name: sys.modules.get(name) for name in _PATCHED_MODULES}
    app_package = importlib.import_module("app")
    saved_attrs = {name: getattr(app_package, name, None) for name in ("config", "db", "registry")}
    try:
        os.environ["APP_ENV"] = "test"
        config = _build_test_config(env_dir)
        sys.modules["app.config"] = config
        app_package.__dict__["config"] = config
        for name in ("app.db", "app.registry"):
            sys.modules.pop(name, None)
        yield
    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for attr, value in saved_attrs.items():  # restore the package attributes we changed
            if value is None:
                if hasattr(app_package, attr):
                    delattr(app_package, attr)
            else:
                setattr(app_package, attr, value)
        os.environ.clear()
        os.environ.update(saved_environ)


@dataclass
class _Registry:
    """The registry module, its session factory, and the documents this test created."""

    registry: Any
    models: Any
    session_local: Any
    created: list[uuid.UUID] = field(default_factory=list)

    def new_doc(self, **overrides: Any) -> uuid.UUID:
        """Create a document with a fresh UUID and track it for cleanup."""
        doc_id = uuid.uuid4()
        values: dict[str, Any] = {
            "doc_id": doc_id,
            "filename": "report.pdf",
            "stored_name": f"{doc_id}.pdf",
            "size_bytes": 2048,
        }
        values.update(overrides)
        with self.session_local() as session:
            self.registry.create_document(session, **values)
        self.created.append(doc_id)
        return doc_id

    def read_doc(self, doc_id: uuid.UUID) -> dict[str, Any] | None:
        """Read a document in a fresh session, so the value is read from MySQL."""
        with self.session_local() as session:
            doc = session.get(self.models.Document, doc_id)
            if doc is None:
                return None
            return {
                "id": doc.id,
                "filename": doc.filename,
                "stored_name": doc.stored_name,
                "size_bytes": doc.size_bytes,
                "status": doc.status,
                "error": doc.error,
                "chunks_total": doc.chunks_total,
                "chunks_done": doc.chunks_done,
                "created_at": doc.created_at,
            }

    def read_chunks(self, doc_id: uuid.UUID) -> list[tuple[uuid.UUID, int, str]]:
        """Return (episode_uuid, chunk_index, state) for one document, read in a fresh session."""
        with self.session_local() as session:
            rows = self.registry.list_tracked_chunks(session, doc_id)
            return [(row.episode_uuid, row.chunk_index, row.state) for row in rows]

    def cleanup(self) -> None:
        """Delete every document this test created. A missing document is a no-op."""
        with self.session_local() as session:
            for doc_id in self.created:
                self.registry.delete_document(session, doc_id)


@pytest.fixture
def reg(_registry_test_settings: None) -> Iterator[_Registry]:
    """Yield the registry with a verified MySQL connection, or skip as not verified."""
    db_module = importlib.import_module("app.db")
    config_module = importlib.import_module("app.config")
    engine = db_module.engine
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        settings = config_module.settings
        pytest.skip(
            f"not verified: MySQL not reachable at {settings.MYSQL_HOST}:{settings.MYSQL_PORT} "
            f"({exc.orig})"
        )

    # Document and InsertionChunk live on the registry module, so it serves as the models namespace.
    registry = importlib.import_module("app.registry")
    db_module.Base.metadata.create_all(engine)
    handle = _Registry(registry=registry, models=registry, session_local=db_module.SessionLocal)
    try:
        yield handle
    finally:
        handle.cleanup()


@pytest.mark.integration
def test_create_document_round_trips_every_field_through_mysql(reg: _Registry) -> None:
    doc_id = reg.new_doc(filename="notes.txt", stored_name="stored-notes.txt", size_bytes=4096)

    row = reg.read_doc(doc_id)

    assert row is not None
    assert row["id"] == doc_id
    assert row["filename"] == "notes.txt"
    assert row["stored_name"] == "stored-notes.txt"
    assert row["size_bytes"] == 4096
    assert row["status"] == "processing"
    assert row["error"] is None
    assert row["chunks_total"] is None
    assert row["chunks_done"] == 0
    assert isinstance(row["created_at"], datetime)


@pytest.mark.integration
def test_set_document_status_done_persists_error_and_chunks_total(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    with reg.session_local() as session:
        reg.registry.set_document_status(
            session, doc_id, "done", error="one chunk needed a retry", chunks_total=3
        )

    row = reg.read_doc(doc_id)

    assert row is not None
    assert row["status"] == "done"
    assert row["error"] == "one chunk needed a retry"
    assert row["chunks_total"] == 3


@pytest.mark.integration
def test_count_documents_increases_by_exactly_one_on_create(reg: _Registry) -> None:
    with reg.session_local() as session:
        before = reg.registry.count_documents(session)

    reg.new_doc()

    with reg.session_local() as session:
        after = reg.registry.count_documents(session)
    assert after == before + 1


@pytest.mark.integration
def test_record_pending_chunks_are_listed_in_chunk_index_order(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    episodes = {index: uuid.uuid4() for index in (2, 0, 1)}
    with reg.session_local() as session:
        for index in (2, 0, 1):
            reg.registry.record_pending_chunk(
                session, episode_uuid=episodes[index], doc_id=doc_id, chunk_index=index
            )

    chunks = reg.read_chunks(doc_id)

    assert chunks == [
        (episodes[0], 0, "pending"),
        (episodes[1], 1, "pending"),
        (episodes[2], 2, "pending"),
    ]


@pytest.mark.integration
def test_mark_chunk_inserted_changes_only_that_row(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    episodes = [uuid.uuid4() for _ in range(3)]
    with reg.session_local() as session:
        for index, episode in enumerate(episodes):
            reg.registry.record_pending_chunk(
                session, episode_uuid=episode, doc_id=doc_id, chunk_index=index
            )
    with reg.session_local() as session:
        reg.registry.mark_chunk_inserted(session, episodes[1])

    chunks = reg.read_chunks(doc_id)

    assert chunks == [
        (episodes[0], 0, "pending"),
        (episodes[1], 1, "inserted"),
        (episodes[2], 2, "pending"),
    ]


@pytest.mark.integration
def test_increment_chunks_done_counts_both_increments(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    with reg.session_local() as session:
        reg.registry.increment_chunks_done(session, doc_id)
        reg.registry.increment_chunks_done(session, doc_id)

    row = reg.read_doc(doc_id)

    assert row is not None
    assert row["chunks_done"] == 2


@pytest.mark.integration
def test_set_document_status_done_is_accepted_and_clears_error(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    with reg.session_local() as session:
        reg.registry.set_document_status(session, doc_id, "failed", error="boom")
    with reg.session_local() as session:
        reg.registry.set_document_status(session, doc_id, "done")

    row = reg.read_doc(doc_id)

    assert row is not None
    assert row["status"] == "done"
    assert row["error"] is None


@pytest.mark.integration
def test_set_document_status_rejects_unknown_status(reg: _Registry) -> None:
    doc_id = reg.new_doc()

    with reg.session_local() as session:
        with pytest.raises(ValueError, match="unknown document status"):
            reg.registry.set_document_status(session, doc_id, "not-a-real-status")

    row = reg.read_doc(doc_id)
    assert row is not None
    assert row["status"] == "processing"


@pytest.mark.integration
def test_set_document_status_raises_lookup_error_for_missing_document(reg: _Registry) -> None:
    with reg.session_local() as session:
        with pytest.raises(LookupError):
            reg.registry.set_document_status(session, uuid.uuid4(), "done")


@pytest.mark.integration
def test_increment_chunks_done_raises_lookup_error_for_missing_document(reg: _Registry) -> None:
    with reg.session_local() as session:
        with pytest.raises(LookupError):
            reg.registry.increment_chunks_done(session, uuid.uuid4())


@pytest.mark.integration
def test_mark_chunk_inserted_raises_lookup_error_for_missing_chunk(reg: _Registry) -> None:
    with reg.session_local() as session:
        with pytest.raises(LookupError):
            reg.registry.mark_chunk_inserted(session, uuid.uuid4())


@pytest.mark.integration
def test_delete_document_cascades_to_tracked_chunks(reg: _Registry) -> None:
    doc_id = reg.new_doc()
    episodes = [uuid.uuid4() for _ in range(3)]
    with reg.session_local() as session:
        for index, episode in enumerate(episodes):
            reg.registry.record_pending_chunk(
                session, episode_uuid=episode, doc_id=doc_id, chunk_index=index
            )
    assert len(reg.read_chunks(doc_id)) == 3

    with reg.session_local() as session:
        deleted = reg.registry.delete_document(session, doc_id)

    assert deleted is True
    assert reg.read_doc(doc_id) is None
    with reg.session_local() as session:
        leftover = session.scalars(
            select(reg.models.InsertionChunk).where(reg.models.InsertionChunk.doc_id == doc_id)
        ).all()
    assert list(leftover) == []


@pytest.mark.integration
def test_delete_document_returns_false_for_missing_document(reg: _Registry) -> None:
    with reg.session_local() as session:
        assert reg.registry.delete_document(session, uuid.uuid4()) is False


@pytest.mark.integration
def test_list_documents_returns_newest_first(reg: _Registry) -> None:
    ids = [reg.new_doc(filename=f"doc-{offset}.txt") for offset in range(3)]
    base = datetime(2001, 1, 1, 12, 0, 0)
    with reg.session_local() as session:
        for offset, doc_id in enumerate(ids):
            doc = session.get(reg.models.Document, doc_id)
            doc.created_at = base + timedelta(minutes=offset)
        session.commit()

    with reg.session_local() as session:
        listed = [doc.id for doc in reg.registry.list_documents(session) if doc.id in set(ids)]

    assert listed == [ids[2], ids[1], ids[0]]
