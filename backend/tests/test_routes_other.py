"""Tests for the system, graph, and chat routes (plan §6.1, §9.3).

The three routers are mounted on one scratch FastAPI app built inside this file.
main.py is never imported, and no lifespan runs. Shared services reach the routes
through each router's own dependency function, so each one is overridden through
`app.dependency_overrides` on its own function object:

- routes_graph.get_graph_service
- routes_chat.get_graph_service, routes_chat.get_event_bus, routes_chat.get_rate_limiter

Settings come from a placeholder `.env.test` in tmp_path, loaded the same way
test_auth.py loads it. The repo env files are never read. The agent's chat model
is replaced by `tests.fakes.FakeChatModel`, so the background task that POST
/api/chat schedules never makes a network call.
"""

import importlib
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fakes import FakeChatModel, FakeGraphService
from fastapi import FastAPI
from fastapi.testclient import TestClient

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

TEST_TOKEN = "test-token-abc-123"
WRONG_TOKEN = "wrong-token-xyz-999"
TOKEN_HEADER = "X-API-Token"

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

# Modules that read app.config at import time. They are re-imported per test
# against the placeholder config, and removed from sys.modules afterwards.
_CONFIG_BOUND_MODULES = (
    "app.auth",
    "app.routes_system",
    "app.routes_graph",
    "app.routes_chat",
    "app.agent",
)


class SpyRateLimiter:
    """Never refuses. Records each key it is asked about, so a test can see whether it ran."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    def allow(self, key: str) -> bool:
        """Record the key and allow the call."""
        self.keys.append(key)
        return True


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """Build the scratch app with all three routers mounted, against a placeholder config."""
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

    app_package = importlib.import_module("app")
    monkeypatch.setitem(sys.modules, "app.config", config)
    monkeypatch.setattr(app_package, "config", config, raising=False)
    for name in _CONFIG_BOUND_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)

    monkeypatch.setattr(config.settings, "API_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(config.settings, "ALLOWED_EXTENSIONS", "pdf,docx,txt")
    monkeypatch.setattr(config.settings, "MAX_DOCUMENTS", 10)
    monkeypatch.setattr(config.settings, "MAX_FILE_SIZE_MB", 5)

    routes_system = importlib.import_module("app.routes_system")
    routes_graph = importlib.import_module("app.routes_graph")
    routes_chat = importlib.import_module("app.routes_chat")
    agent = importlib.import_module("app.agent")
    graph = importlib.import_module("app.graph")
    events = importlib.import_module("app.events")
    ratelimit = importlib.import_module("app.ratelimit")

    app = FastAPI()
    app.include_router(routes_system.router)
    app.include_router(routes_graph.router)
    app.include_router(routes_chat.router)

    # Every chat dependency is resolved before the body is validated, so all three are
    # wired here. A test that needs a different limiter overrides only that one.
    fake_graph = FakeGraphService()
    bus = events.EventBus()
    app.dependency_overrides[routes_graph.get_graph_service] = lambda: fake_graph
    app.dependency_overrides[routes_chat.get_graph_service] = lambda: fake_graph
    app.dependency_overrides[routes_chat.get_event_bus] = lambda: bus
    app.dependency_overrides[routes_chat.get_rate_limiter] = lambda: ratelimit.RateLimiter()

    yield SimpleNamespace(
        app=app,
        routes_graph=routes_graph,
        routes_chat=routes_chat,
        agent=agent,
        graph=graph,
        fake_graph=fake_graph,
        events=events,
        ratelimit=ratelimit,
    )

    for name in _CONFIG_BOUND_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def fake_llm(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> FakeChatModel:
    """Replace the agent chat model so the chat background task never reaches the network."""
    llm = FakeChatModel(invoke_reply="YES", stream_tokens=["answer"])
    monkeypatch.setattr(env.agent, "build_agent_llm", lambda *args, **kwargs: llm)
    monkeypatch.setattr(env.agent, "build_expand_llm", lambda *args, **kwargs: llm)
    return llm


@pytest.fixture
def fake_graph(env: SimpleNamespace) -> FakeGraphService:
    """The in-memory graph the routes use. It has no facts, so the agent never queries MySQL."""
    fake: FakeGraphService = env.fake_graph
    return fake


@pytest.fixture
def client(env: SimpleNamespace) -> TestClient:
    """A TestClient over the scratch app."""
    return TestClient(env.app)


# --- System routes -------------------------------------------------------------


def test_health_returns_ok_without_token(client: TestClient) -> None:
    """GET /api/health returns 200 with status ok and needs no X-API-Token header."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_config_rejects_missing_token(client: TestClient) -> None:
    """GET /api/config returns 401 when no X-API-Token header is sent."""
    response = client.get("/api/config")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid API token."


def test_config_returns_limits_with_correct_token(client: TestClient) -> None:
    """GET /api/config returns the limits, with allowed_extensions split into a list."""
    response = client.get("/api/config", headers={TOKEN_HEADER: TEST_TOKEN})

    assert response.status_code == 200
    assert response.json() == {
        "max_documents": 10,
        "max_file_size_mb": 5,
        "allowed_extensions": ["pdf", "docx", "txt"],
    }


# --- Graph route ---------------------------------------------------------------


def test_graph_rejects_missing_token(client: TestClient, fake_graph: FakeGraphService) -> None:
    """GET /api/graph returns 401 with no token or a wrong one, and takes no snapshot."""
    missing = client.get("/api/graph")
    wrong = client.get("/api/graph", headers={TOKEN_HEADER: WRONG_TOKEN})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert fake_graph.snapshot_calls == 0


def test_graph_returns_snapshot_nodes_and_edges(env: SimpleNamespace, client: TestClient) -> None:
    """GET /api/graph with the token returns the snapshot's nodes and edges field for field."""
    snapshot_module = env.graph
    fake_graph = FakeGraphService(
        snapshot_result=snapshot_module.GraphSnapshot(
            nodes=[
                snapshot_module.SnapshotNode(id="node-a", name="Alice"),
                snapshot_module.SnapshotNode(id="node-b", name="Bob"),
            ],
            edges=[
                snapshot_module.SnapshotEdge(
                    id="edge-1",
                    name="KNOWS",
                    fact="Alice knows Bob",
                    source_id="node-a",
                    target_id="node-b",
                ),
            ],
        )
    )
    env.app.dependency_overrides[env.routes_graph.get_graph_service] = lambda: fake_graph

    response = client.get("/api/graph", headers={TOKEN_HEADER: TEST_TOKEN})

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [
            {"id": "node-a", "name": "Alice"},
            {"id": "node-b", "name": "Bob"},
        ],
        "edges": [
            {
                "id": "edge-1",
                "name": "KNOWS",
                "fact": "Alice knows Bob",
                "source_id": "node-a",
                "target_id": "node-b",
            },
        ],
    }
    assert fake_graph.snapshot_calls == 1


# --- Chat route ----------------------------------------------------------------


def test_chat_rejects_missing_token_before_any_side_effect(
    env: SimpleNamespace,
    client: TestClient,
    fake_graph: FakeGraphService,
    fake_llm: FakeChatModel,
) -> None:
    """POST /api/chat returns 401 without a token. The limiter and agent are never reached."""
    limiter = SpyRateLimiter()
    env.app.dependency_overrides[env.routes_chat.get_rate_limiter] = lambda: limiter

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 401
    assert limiter.keys == []
    assert fake_graph.retrieve_queries == []
    assert fake_llm.invoke_calls == []
    assert fake_llm.stream_calls == []


def test_chat_rejects_whitespace_only_message_without_agent_run(
    env: SimpleNamespace,
    client: TestClient,
    fake_graph: FakeGraphService,
    fake_llm: FakeChatModel,
) -> None:
    """POST /api/chat returns 422 for a whitespace-only message and starts no agent run."""
    limiter = SpyRateLimiter()
    env.app.dependency_overrides[env.routes_chat.get_rate_limiter] = lambda: limiter

    response = client.post(
        "/api/chat",
        json={"message": "   "},
        headers={TOKEN_HEADER: TEST_TOKEN},
    )

    assert response.status_code == 422
    assert limiter.keys == []
    assert fake_graph.retrieve_queries == []
    assert fake_llm.invoke_calls == []
    assert fake_llm.stream_calls == []


def test_chat_rejects_missing_message_field(client: TestClient, fake_llm: FakeChatModel) -> None:
    """POST /api/chat returns 422 when the body has no message field at all."""
    response = client.post("/api/chat", json={}, headers={TOKEN_HEADER: TEST_TOKEN})

    assert response.status_code == 422
    assert fake_llm.invoke_calls == []
    assert fake_llm.stream_calls == []


def test_chat_accepts_message_and_returns_chat_id_uuid(
    env: SimpleNamespace,
    client: TestClient,
    fake_graph: FakeGraphService,
    fake_llm: FakeChatModel,
) -> None:
    """POST /api/chat returns 202 with a UUID chat_id, and the background run completes."""
    response = client.post(
        "/api/chat",
        json={"message": "What does the report say?"},
        headers={TOKEN_HEADER: TEST_TOKEN},
    )

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"chat_id"}
    parsed = uuid.UUID(body["chat_id"])
    assert parsed.version == 4
    # TestClient runs background tasks before the response returns, so the agent has run.
    assert fake_graph.retrieve_queries != []
    assert len(fake_llm.stream_calls) >= 1


def test_chat_second_call_over_limit_returns_429_without_new_run(
    env: SimpleNamespace,
    client: TestClient,
    fake_graph: FakeGraphService,
    fake_llm: FakeChatModel,
) -> None:
    """With a limit of one call, a second POST with the same token returns 429 and starts no run."""
    limiter = env.ratelimit.RateLimiter(max_requests=1)
    env.app.dependency_overrides[env.routes_chat.get_rate_limiter] = lambda: limiter
    headers = {TOKEN_HEADER: TEST_TOKEN}

    first = client.post("/api/chat", json={"message": "first"}, headers=headers)
    assert first.status_code == 202
    assert "chat_id" in first.json()
    retrieves_after_first = len(fake_graph.retrieve_queries)
    streams_after_first = len(fake_llm.stream_calls)

    second = client.post("/api/chat", json={"message": "second"}, headers=headers)

    assert second.status_code == 429
    assert "chat_id" not in second.json()
    assert len(fake_graph.retrieve_queries) == retrieves_after_first
    assert len(fake_llm.stream_calls) == streams_after_first
