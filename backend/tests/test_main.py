"""Tests for the app.main lifespan: startup order and storage setup (plan §6.5, §6.10, §9.3, T2.29).

app/main.py's lifespan runs on every boot, in this order:
1. create the DATA_DIR/uploads directory;
2. create the MySQL tables;
3. start the graph service;
4. run startup recovery, which must finish before the app serves requests.
Any failure in those steps propagates and stops startup. The graph service is
closed on shutdown.

These tests run the real lifespan with no live service. create_all, GraphService
and run_startup_recovery are replaced on the app.main module with fakes that
append to one shared order list. EventBus and RateLimiter do no I/O, so they run
for real. The DATA_DIR/uploads mkdir is real, and it writes only under tmp_path.

app.main is imported against a fake app.config built from a placeholder
.env.test in tmp_path, the same way tests/test_main_errors.py does it. The real
repo env files are never read.
"""

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

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
    "AGENT_LLM_EXPAND_BASE_URL": "http://expand.invalid/v1",
    "AGENT_LLM_EXPAND_API_KEY": "placeholder-expand-key",
    "AGENT_LLM_EXPAND_MODEL": "placeholder-expand-model",
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


def _load_fake_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, values: dict[str, Any]
) -> ModuleType:
    """Build app.config from app/config.py source, reading only a .env.test in tmp_path.

    The final `settings = load_settings()` line is removed, so nothing loads at exec
    time. The caller decides when load_settings() runs. Every required key is also
    removed from the process environment copy, so only the file can supply values.
    """
    env_text = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    (tmp_path / ".env.test").write_text(env_text, encoding="utf-8")

    env = dict(os.environ)
    for key in ENV_VALUES:
        env.pop(key, None)
    env["APP_ENV"] = "test"
    monkeypatch.setattr(os, "environ", env)

    source = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "\nsettings = load_settings()\n"
    assert source.count(marker) == 1, "app/config.py must end with one module-level load_settings()"
    source = source.replace(marker, "\n")
    config = ModuleType("app.config")
    config.__file__ = str(tmp_path / "backend" / "app" / "config.py")
    exec(compile(source, config.__file__, "exec"), config.__dict__)
    return config


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A DATA_DIR inside tmp_path that does not exist yet."""
    return tmp_path / "data"


@pytest.fixture
def main_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> Iterator[ModuleType]:
    """Yield app.main, imported against a fake app.config whose DATA_DIR is inside tmp_path.

    Only the import happens here. The lifespan runs only when a test opens TestClient.
    """
    values = {**ENV_VALUES, "DATA_DIR": str(data_dir)}
    config = _load_fake_config(tmp_path, monkeypatch, values)
    config.__dict__["settings"] = config.__dict__["load_settings"]()

    app_package = importlib.import_module("app")
    monkeypatch.setitem(sys.modules, "app.config", config)
    monkeypatch.setattr(app_package, "config", config, raising=False)

    # Remember which app.* modules exist now, so every module imported here can be removed.
    app_modules_before = {name for name in sys.modules if name.startswith("app.")}
    monkeypatch.delitem(sys.modules, "app.main", raising=False)
    main = importlib.import_module("app.main")

    yield main

    for name in list(sys.modules):
        if name.startswith("app.") and name not in app_modules_before and name != "app.config":
            sys.modules.pop(name, None)


class _Recorder:
    """Shared record of every startup and shutdown step, in call order."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.graph_instances: list[object] = []
        self.recovery_graphs: list[object] = []
        self.closed_graphs: list[object] = []


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def fake_steps(
    main_module: ModuleType, recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> ModuleType:
    """Replace the three I/O steps in app.main's lifespan with fakes that record their calls."""

    class FakeGraphService:
        def __init__(self) -> None:
            recorder.graph_instances.append(self)

        async def start(self) -> None:
            recorder.events.append("graph.start")

        async def close(self) -> None:
            recorder.events.append("graph.close")
            recorder.closed_graphs.append(self)

    def fake_create_all() -> None:
        recorder.events.append("create_all")

    async def fake_run_startup_recovery(graph: object) -> int:
        recorder.events.append("run_startup_recovery")
        recorder.recovery_graphs.append(graph)
        return 0

    monkeypatch.setattr(main_module, "create_all", fake_create_all)
    monkeypatch.setattr(main_module, "GraphService", FakeGraphService)
    monkeypatch.setattr(main_module, "run_startup_recovery", fake_run_startup_recovery)
    return main_module


def test_missing_required_variable_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading settings with one required variable absent raises and names that variable."""
    values = {key: value for key, value in ENV_VALUES.items() if key != "NEO4J_PASSWORD"}
    config = _load_fake_config(tmp_path, monkeypatch, values)

    with pytest.raises(ValidationError) as excinfo:
        config.__dict__["load_settings"]()

    assert "NEO4J_PASSWORD" in str(excinfo.value)


def test_valid_settings_create_data_dir_uploads(
    main_module: ModuleType, fake_steps: ModuleType, data_dir: Path
) -> None:
    """With complete settings, startup creates DATA_DIR/uploads, even when DATA_DIR is new."""
    uploads = Path(main_module.settings.DATA_DIR, "uploads")
    assert not data_dir.exists()

    with TestClient(main_module.app):
        assert uploads.is_dir()

    assert uploads == data_dir / "uploads"


def test_startup_runs_steps_in_order_before_first_request(
    main_module: ModuleType, fake_steps: ModuleType, recorder: _Recorder
) -> None:
    """Tables, graph start and recovery all run, in that order, before a request is served."""
    with TestClient(main_module.app) as client:
        assert recorder.events == ["create_all", "graph.start", "run_startup_recovery"]

        recorder.events.append("request")
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert recorder.events == [
            "create_all",
            "graph.start",
            "run_startup_recovery",
            "request",
        ]


def test_recovery_receives_the_graph_started_by_lifespan(
    main_module: ModuleType, fake_steps: ModuleType, recorder: _Recorder
) -> None:
    """Recovery gets the same graph instance that lifespan created and started."""
    with TestClient(main_module.app):
        assert len(recorder.graph_instances) == 1
        assert len(recorder.recovery_graphs) == 1
        assert recorder.recovery_graphs[0] is recorder.graph_instances[0]


def test_shutdown_closes_the_graph_service(
    main_module: ModuleType, fake_steps: ModuleType, recorder: _Recorder
) -> None:
    """Leaving the TestClient block shuts the app down and closes the same graph instance."""
    with TestClient(main_module.app):
        assert recorder.closed_graphs == []

    assert len(recorder.closed_graphs) == 1
    assert recorder.closed_graphs[0] is recorder.graph_instances[0]
    assert recorder.events[-1] == "graph.close"


def test_recovery_failure_stops_startup_and_propagates(
    main_module: ModuleType, fake_steps: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in recovery is raised out of startup, so no request is served."""

    async def failing_recovery(graph: object) -> int:
        raise RuntimeError("recovery failed")

    monkeypatch.setattr(main_module, "run_startup_recovery", failing_recovery)

    with pytest.raises(RuntimeError, match="recovery failed"):
        with TestClient(main_module.app):
            pass
