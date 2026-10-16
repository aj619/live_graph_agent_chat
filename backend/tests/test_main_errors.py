"""Tests for the global unhandled-exception handler in app.main (plan §9.3, T2.29).

``unhandled_exception_handler`` in app/main.py must log the full traceback and
return a generic 500 JSON body, ``{"detail": "Internal server error."}``, with
no exception text in it.

Two checks cover it:

1. Direct calls. The handler is an ordinary async function, so each test awaits
   it with a real ``starlette.requests.Request`` built from a raw ASGI scope and
   a real exception instance. This proves the handler's own behaviour.
2. A scratch FastAPI app. It registers only the real handler (no
   SecurityHeadersMiddleware) and has one route that raises. TestClient runs
   with ``raise_server_exceptions=False``, so the test sees the HTTP response
   the handler produced.

The composed ``app.main.app`` is never used here. In that app,
SecurityHeadersMiddleware catches route exceptions before this handler runs
(see the module docstring of app/security_headers.py). Those tests belong to
T2.T16. The lifespan is never started, so no Neo4j or MySQL is needed.

app.main is imported with a fake app.config built from a placeholder .env.test
in tmp_path, the same way tests/test_logging.py does it. The real repo env
files are never read.
"""

import asyncio
import importlib
import json
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

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

SECRET_TEXT = "secret internal detail"
EXPECTED_BODY = {"detail": "Internal server error."}


@pytest.fixture
def main_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Yield app.main, imported against a fake app.config built from tmp_path.

    Only the module is imported. Its lifespan is never run, so no service is needed.
    """
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

    # Remember which app.* modules exist now, so every module imported here can be removed.
    app_modules_before = {name for name in sys.modules if name.startswith("app.")}
    monkeypatch.delitem(sys.modules, "app.main", raising=False)
    main = importlib.import_module("app.main")

    yield main

    for name in list(sys.modules):
        if name.startswith("app.") and name not in app_modules_before and name != "app.config":
            sys.modules.pop(name, None)


def _raw_request(path: str = "/boom", method: str = "GET") -> Request:
    """Build a real starlette Request from a minimal HTTP ASGI scope."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    return Request(scope)


def test_handler_returns_json_response_with_status_500(main_module: ModuleType) -> None:
    """The handler returns a JSONResponse whose status code is 500."""
    response = asyncio.run(
        main_module.unhandled_exception_handler(_raw_request(), RuntimeError(SECRET_TEXT))
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500


def test_handler_body_is_exactly_the_generic_detail(main_module: ModuleType) -> None:
    """The response body is exactly the generic detail JSON, with no other keys."""
    response = asyncio.run(
        main_module.unhandled_exception_handler(_raw_request(), RuntimeError(SECRET_TEXT))
    )

    assert json.loads(bytes(response.body)) == EXPECTED_BODY
    assert main_module.GENERIC_ERROR_DETAIL == "Internal server error."


def test_handler_body_never_contains_exception_text(main_module: ModuleType) -> None:
    """The exception message and its class name never appear in the response body."""
    response = asyncio.run(
        main_module.unhandled_exception_handler(_raw_request(), RuntimeError(SECRET_TEXT))
    )

    body_text = bytes(response.body).decode("utf-8")
    assert SECRET_TEXT not in body_text
    assert "RuntimeError" not in body_text
    assert "Traceback" not in body_text


def test_handler_logs_error_with_method_and_path(
    main_module: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    """The handler logs one ERROR record whose message names only the method and path."""
    with caplog.at_level(logging.ERROR, logger="app.main"):
        asyncio.run(
            main_module.unhandled_exception_handler(
                _raw_request(path="/documents/upload", method="POST"),
                RuntimeError(SECRET_TEXT),
            )
        )

    records = [record for record in caplog.records if record.name == "app.main"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == "unhandled exception on POST /documents/upload"
    assert SECRET_TEXT not in record.getMessage()


def test_handler_puts_full_exception_in_exc_info(
    main_module: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    """The exception itself is attached as exc_info, so the traceback is logged separately."""
    exc = RuntimeError(SECRET_TEXT)
    with caplog.at_level(logging.ERROR, logger="app.main"):
        asyncio.run(main_module.unhandled_exception_handler(_raw_request(), exc))

    record = next(record for record in caplog.records if record.name == "app.main")
    assert record.exc_info is not None
    assert record.exc_info[1] is exc


def test_scratch_app_with_real_handler_returns_generic_500(main_module: ModuleType) -> None:
    """Over HTTP, a route that raises gets the generic 500 from the real handler.

    The scratch app has no SecurityHeadersMiddleware, so nothing intercepts first.
    """
    scratch_app = FastAPI()
    scratch_app.add_exception_handler(Exception, main_module.unhandled_exception_handler)

    @scratch_app.get("/boom")
    def boom() -> None:
        raise RuntimeError(SECRET_TEXT)

    client = TestClient(scratch_app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == EXPECTED_BODY
    assert SECRET_TEXT not in response.text
    assert "Traceback" not in response.text
