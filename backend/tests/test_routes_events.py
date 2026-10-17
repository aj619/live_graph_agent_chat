"""Tests for the GET /api/events SSE route (plan §6.1, §6.2).

The route is `app.routes_events.get_events`. Its body is `app.events.stream_events`
passed through unchanged, so these tests check the wiring: the token guard, the
headers, and that the blocks reach the client byte for byte, in publish order, as
they are published.

Streaming is driven without httpx's ASGI transport. `httpx.ASGITransport` runs the
app to completion and buffers the whole body before it returns, so an endless SSE
stream would never return to the test. Instead the async tests call the ASGI app
directly as a background task, with their own `receive` and `send`. Each body
chunk is handed to the test as it is sent, so the test can publish between reads.

The 401 cases use the synchronous TestClient, because a 401 short-circuits before
any streaming body is produced.

`app.routes_events` imports `app.auth`, and `app.auth` reads `settings` from
`app.config` when it is imported. So the module is loaded per test against a
placeholder config, the same way tests/test_auth.py does it. No .env file and no
live service is needed. Every await that could hang has a short timeout.
"""

import asyncio
import importlib
import json
import os
import sys
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.events import CONNECTED_COMMENT, EventBus, format_sse

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

TEST_TOKEN = "test-token-abc-123"
WRONG_TOKEN = "wrong-token-xyz-999"
ROUTE_PATH = "/api/events"
READ_TIMEOUT = 2.0

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


@pytest.fixture
def routes_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Yield app.routes_events loaded against a placeholder config with API_TOKEN = TEST_TOKEN."""
    env_text = "\n".join(f"{key}={value}" for key, value in ENV_VALUES.items()) + "\n"
    (tmp_path / ".env.test").write_text(env_text, encoding="utf-8")

    env = dict(os.environ)
    env["APP_ENV"] = "test"
    monkeypatch.setattr(os, "environ", env)

    # Execute app/config.py with the final load line removed, under a fake __file__,
    # so REPO_ROOT resolves to tmp_path and the real repo env files are never read.
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
    monkeypatch.delitem(sys.modules, "app.auth", raising=False)
    monkeypatch.delitem(sys.modules, "app.routes_events", raising=False)
    monkeypatch.setattr(config.settings, "API_TOKEN", TEST_TOKEN)
    routes = importlib.import_module("app.routes_events")

    yield routes

    sys.modules.pop("app.routes_events", None)
    sys.modules.pop("app.auth", None)


def _build_app(routes: ModuleType, bus: EventBus) -> FastAPI:
    """Mount the real events router on a scratch app, with the bus overridden by the test's bus."""
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_event_bus] = lambda: bus
    return app


# --- 401 without a valid token (synchronous TestClient) ----------------------


def test_events_route_rejects_missing_token_with_401(routes_module: ModuleType) -> None:
    client = TestClient(_build_app(routes_module, EventBus()))

    response = client.get(ROUTE_PATH)

    assert response.status_code == 401


def test_events_route_rejects_wrong_token_with_401(routes_module: ModuleType) -> None:
    client = TestClient(_build_app(routes_module, EventBus()))

    response = client.get(ROUTE_PATH, headers={"X-API-Token": WRONG_TOKEN})

    assert response.status_code == 401


# --- Streaming over an ASGI driver with a background task -------------------


@dataclass
class _OpenStream:
    """One open GET /api/events, driven by the test while the app streams in a task."""

    task: asyncio.Task[None]
    status: int
    headers: dict[str, str]
    _body: asyncio.Queue[bytes]
    _disconnected: asyncio.Event
    _buffer: bytes = field(default=b"")

    async def read_block(self) -> str:
        """Return the next complete SSE block, including its trailing blank line."""
        while b"\n\n" not in self._buffer:
            chunk = await asyncio.wait_for(self._body.get(), timeout=READ_TIMEOUT)
            self._buffer += chunk
        end = self._buffer.index(b"\n\n") + 2
        block, self._buffer = self._buffer[:end], self._buffer[end:]
        return block.decode("utf-8")

    async def disconnect(self) -> None:
        """Simulate the client going away, then wait for the app to finish. Re-raises app errors."""
        self._disconnected.set()
        await asyncio.wait_for(self.task, timeout=READ_TIMEOUT)


async def _open_stream(app: FastAPI, token: str | None) -> _OpenStream:
    """Call the ASGI app for GET /api/events in a task and return once the response has started."""
    body: asyncio.Queue[bytes] = asyncio.Queue()
    started: asyncio.Event = asyncio.Event()
    disconnected = asyncio.Event()
    state: dict[str, Any] = {"status": 0, "headers": {}, "request_sent": False}

    headers: list[tuple[bytes, bytes]] = [(b"host", b"test")]
    if token is not None:
        headers.append((b"x-api-token", token.encode("utf-8")))
    scope: MutableMapping[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": ROUTE_PATH,
        "raw_path": ROUTE_PATH.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("test", 80),
        "state": {},
    }

    async def receive() -> MutableMapping[str, Any]:
        if not state["request_sent"]:
            state["request_sent"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
            state["headers"] = {
                name.decode("latin-1").lower(): value.decode("latin-1")
                for name, value in message.get("headers", [])
            }
            started.set()
        elif message["type"] == "http.response.body":
            chunk: bytes = message.get("body", b"")
            if chunk:
                body.put_nowait(chunk)

    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(started.wait(), timeout=READ_TIMEOUT)
    return _OpenStream(
        task=task,
        status=state["status"],
        headers=state["headers"],
        _body=body,
        _disconnected=disconnected,
    )


async def test_events_stream_starts_with_connected_comment_before_any_event(
    routes_module: ModuleType,
) -> None:
    bus = EventBus()
    stream = await _open_stream(_build_app(routes_module, bus), TEST_TOKEN)
    try:
        assert stream.status == 200

        first = await stream.read_block()

        assert first == CONNECTED_COMMENT
    finally:
        await stream.disconnect()


async def test_events_stream_response_is_event_stream_with_no_cache(
    routes_module: ModuleType,
) -> None:
    bus = EventBus()
    stream = await _open_stream(_build_app(routes_module, bus), TEST_TOKEN)
    try:
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-cache"
    finally:
        await stream.disconnect()


async def test_events_stream_delivers_published_events_in_order_as_exact_blocks(
    routes_module: ModuleType,
) -> None:
    bus = EventBus()
    stream = await _open_stream(_build_app(routes_module, bus), TEST_TOKEN)
    try:
        assert await stream.read_block() == CONNECTED_COMMENT

        # Publish one event, read it, then publish the next. Each block must arrive
        # as it is published, in order, and match format_sse byte for byte.
        bus.publish("test.event", {"n": 1})
        first_block = await stream.read_block()
        bus.publish("test.event", {"n": 2})
        second_block = await stream.read_block()

        assert first_block == format_sse("test.event", {"n": 1})
        assert second_block == format_sse("test.event", {"n": 2})

        data_line = next(line for line in first_block.split("\n") if line.startswith("data: "))
        assert json.loads(data_line.removeprefix("data: ")) == {"n": 1}
    finally:
        await stream.disconnect()


async def test_events_stream_closes_cleanly_when_client_disconnects(
    routes_module: ModuleType,
) -> None:
    bus = EventBus()
    stream = await _open_stream(_build_app(routes_module, bus), TEST_TOKEN)

    assert await stream.read_block() == CONNECTED_COMMENT
    bus.publish("test.event", {"n": 1})
    assert await stream.read_block() == format_sse("test.event", {"n": 1})

    # Disconnecting must end the app task without raising, and must release the subscription.
    await stream.disconnect()

    assert stream.task.done()
    assert stream.task.exception() is None
    assert bus.subscriber_count == 0
