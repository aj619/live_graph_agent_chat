"""Tests for the secret-redacting structured logging in app.logging_setup (plan §6.10).

app.logging_setup reads live values from app.config.settings, and app.config
loads the selected env file at import time. These tests must never touch the
real repo env files, so they do not import app.config or app.logging_setup at
module level. Each test builds its own app.config from source under a fake
__file__ inside pytest's tmp_path, with a minimal placeholder .env.test there.
Then it imports app.logging_setup against that config. os.environ is swapped for
a copy for the duration of the test, so the exported values cannot leak.

The tests read the formatted output line from a StringIO handler that uses the
production KeyValueFormatter and SecretRedactingFilter, so they check the exact
line that would reach the log, not the record object.

backend/ is on sys.path through tests/conftest.py, so no sys.path shim is needed.
"""

import importlib
import io
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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

LOGGER = logging.getLogger("lgac.test.redaction")


@pytest.fixture
def logging_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[ModuleType, ModuleType]]:
    """Yield (app.logging_setup, app.config) built against a placeholder .env.test in tmp_path."""
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
    monkeypatch.delitem(sys.modules, "app.logging_setup", raising=False)
    logging_setup_module = importlib.import_module("app.logging_setup")

    # Restore the root logger's handlers and level after each test.
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    yield logging_setup_module, config

    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
    root.setLevel(saved_level)
    sys.modules.pop("app.logging_setup", None)


def _capture(logging_setup_module: ModuleType) -> io.StringIO:
    """Install the production handler on the root logger, writing to a StringIO."""
    stream = io.StringIO()
    logging_setup_module.configure_logging(stream=stream)
    return stream


def test_logged_api_token_shows_as_stars_in_formatted_line(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "secret-value-xyz")
    stream = _capture(logging_setup_module)

    LOGGER.info("token is %s", config.settings.API_TOKEN)

    line = stream.getvalue()
    assert "secret-value-xyz" not in line
    assert 'msg="token is ***"' in line


def test_secret_in_extra_field_is_redacted_in_formatted_line(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "secret-value-xyz")
    stream = _capture(logging_setup_module)

    LOGGER.info("request done", extra={"custom_field": config.settings.API_TOKEN})

    line = stream.getvalue()
    assert "secret-value-xyz" not in line
    assert "custom_field=***" in line


def test_secret_in_exception_traceback_is_redacted(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "secret-value-xyz")
    stream = _capture(logging_setup_module)

    token = config.settings.API_TOKEN
    try:
        raise RuntimeError(token)
    except RuntimeError:
        LOGGER.exception("operation failed")

    line = stream.getvalue()
    assert "secret-value-xyz" not in line
    assert "RuntimeError: ***" in line
    assert 'msg="operation failed"' in line


def test_multiple_distinct_secrets_in_one_message_are_all_redacted(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "token-aaa-111")
    monkeypatch.setattr(config.settings, "MYSQL_PASSWORD", "pw-bbb-222")
    stream = _capture(logging_setup_module)

    LOGGER.info("pair %s and %s", config.settings.API_TOKEN, config.settings.MYSQL_PASSWORD)

    line = stream.getvalue()
    assert "token-aaa-111" not in line
    assert "pw-bbb-222" not in line
    assert 'msg="pair *** and ***"' in line


def test_longer_secret_containing_shorter_secret_is_replaced_whole(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "abc")
    monkeypatch.setattr(config.settings, "MYSQL_PASSWORD", "abcdef")
    stream = _capture(logging_setup_module)

    LOGGER.info("password is %s", config.settings.MYSQL_PASSWORD)

    line = stream.getvalue()
    # Longest first: the whole "abcdef" becomes one ***, with no leftover "def".
    assert 'msg="password is ***"' in line
    assert "def" not in line
    assert "abc" not in line


def test_message_without_secret_passes_through_unchanged(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "API_TOKEN", "secret-value-xyz")
    stream = _capture(logging_setup_module)

    LOGGER.info("service started on port 8000")

    line = stream.getvalue()
    assert 'msg="service started on port 8000"' in line
    assert "***" not in line
    assert logging_setup_module.redact("plain ordinary text") == "plain ordinary text"


def test_empty_secret_value_is_excluded_from_current_secret_values(
    logging_setup: tuple[ModuleType, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    logging_setup_module, config = logging_setup
    monkeypatch.setattr(config.settings, "MYSQL_PASSWORD", "")
    monkeypatch.setattr(config.settings, "API_TOKEN", "secret-value-xyz")

    values = logging_setup_module.current_secret_values()

    assert "" not in values
    assert "secret-value-xyz" in values
    # An empty secret would insert *** between every character, so it must not change text.
    assert logging_setup_module.redact("hello") == "hello"


def test_configure_logging_twice_logs_each_message_once(
    logging_setup: tuple[ModuleType, ModuleType],
) -> None:
    logging_setup_module, _config = logging_setup
    stream = io.StringIO()
    logging_setup_module.configure_logging(stream=stream)
    logging_setup_module.configure_logging(stream=stream)

    root = logging.getLogger()
    installed = [
        handler
        for handler in root.handlers
        if handler.get_name() == logging_setup_module.HANDLER_NAME
    ]
    assert len(installed) == 1

    LOGGER.info("unique-marker-123")

    assert stream.getvalue().count("unique-marker-123") == 1
