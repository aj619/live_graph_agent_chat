"""Tests for the shared-token check in app.auth (plan §6.4).

app.auth reads settings.API_TOKEN from app.config, and app.config loads the
selected env file at import time. These tests must never touch the real repo
env files, so they do not import app.auth or app.config at module level. The
fixture below builds its own app.config from source under a fake __file__ inside
pytest's tmp_path, with a minimal placeholder .env.test there, then imports
app.auth against that config. The same pattern is used in test_logging.py.

Two levels are covered:
- Level 1 calls require_api_token directly as a plain Python function.
- Level 2 mounts it on a small scratch FastAPI app built inside this file, so the
  Header injection path is exercised through TestClient. No project routes are
  imported.

backend/ is on sys.path through tests/conftest.py, so no sys.path shim is needed.
"""

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

TEST_TOKEN = "test-token-abc-123"
WRONG_TOKEN = "wrong-token-xyz-999"
MISSING_DETAIL = "Missing or invalid API token."

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


@pytest.fixture
def auth_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Yield app.auth built against a placeholder config, with API_TOKEN set to TEST_TOKEN."""
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
    auth = importlib.import_module("app.auth")

    monkeypatch.setattr(config.settings, "API_TOKEN", TEST_TOKEN)

    yield auth

    sys.modules.pop("app.auth", None)


def _scratch_app() -> FastAPI:
    """Build a tiny app: /health without the token, /protected with it. No project routes."""
    from app.auth import require_api_token

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/protected", dependencies=[Depends(require_api_token)])
    def protected() -> dict[str, str]:
        return {"status": "allowed"}

    return app


# ---- Level 1: require_api_token called directly as a plain function ----


def test_missing_token_raises_401(auth_module: ModuleType) -> None:
    with pytest.raises(HTTPException) as info:
        auth_module.require_api_token(x_api_token=None)

    assert info.value.status_code == 401


def test_wrong_token_raises_401(auth_module: ModuleType) -> None:
    with pytest.raises(HTTPException) as info:
        auth_module.require_api_token(x_api_token=WRONG_TOKEN)

    assert info.value.status_code == 401


def test_correct_token_returns_none(auth_module: ModuleType) -> None:
    result = auth_module.require_api_token(x_api_token=TEST_TOKEN)

    assert result is None


def test_401_detail_is_fixed_message_and_never_echoes_sent_token(
    auth_module: ModuleType,
) -> None:
    with pytest.raises(HTTPException) as info:
        auth_module.require_api_token(x_api_token=WRONG_TOKEN)

    assert info.value.detail == MISSING_DETAIL
    assert WRONG_TOKEN not in str(info.value.detail)


def test_token_of_different_length_returns_401_without_crashing(
    auth_module: ModuleType,
) -> None:
    for candidate in ["x", TEST_TOKEN + "-extra-suffix", "a" * 5000]:
        with pytest.raises(HTTPException) as info:
            auth_module.require_api_token(x_api_token=candidate)
        assert info.value.status_code == 401


def test_non_ascii_token_returns_401_without_type_or_encode_error(
    auth_module: ModuleType,
) -> None:
    for candidate in ["tóken-with-accent", "token-with-emoji-🔑", "日本語トークン"]:
        with pytest.raises(HTTPException) as info:
            auth_module.require_api_token(x_api_token=candidate)
        assert info.value.status_code == 401
        assert info.value.detail == MISSING_DETAIL


# ---- Level 2: the dependency mounted on a scratch FastAPI app via TestClient ----


def test_health_without_token_returns_200(auth_module: ModuleType) -> None:
    client = TestClient(_scratch_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_without_token_header_returns_401(auth_module: ModuleType) -> None:
    client = TestClient(_scratch_app())

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_DETAIL}


def test_protected_with_wrong_token_header_returns_401(auth_module: ModuleType) -> None:
    client = TestClient(_scratch_app())

    response = client.get("/protected", headers={"X-API-Token": WRONG_TOKEN})

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_DETAIL}
    assert WRONG_TOKEN not in response.text


def test_protected_with_correct_token_header_returns_200(auth_module: ModuleType) -> None:
    client = TestClient(_scratch_app())

    response = client.get("/protected", headers={"X-API-Token": TEST_TOKEN})

    assert response.status_code == 200
    assert response.json() == {"status": "allowed"}


def test_protected_with_different_length_token_header_returns_401(
    auth_module: ModuleType,
) -> None:
    client = TestClient(_scratch_app())

    response = client.get("/protected", headers={"X-API-Token": "short"})

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_DETAIL}


def test_protected_with_non_ascii_token_header_returns_401_not_500(
    auth_module: ModuleType,
) -> None:
    client = TestClient(_scratch_app())

    # httpx sends str header values as ASCII, so the UTF-8 bytes form is used to reach the server.
    response = client.get("/protected", headers={b"X-API-Token": "tóken-é".encode()})

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_DETAIL}
