"""Tests for app.config env-file selection and required-field validation (plan §5).

app.config runs load_settings() at import time, and that call reads the real
repo env file. These tests must never touch the real repo files, so they do
not import app.config. Instead they execute the module source with the final
`settings = load_settings()` line removed, under a fake __file__ inside a
pytest tmp_path. REPO_ROOT then resolves to that tmp_path, so every env file
the tests read or write lives in tmp_path. os.environ is swapped for a copy
for the duration of each test, so load_settings() exporting values cannot
leak into other tests.
"""

import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

# Harmless placeholder values for every required field in plan §5. Keys are
# the field names; values are typed the way Settings declares them.
VALUES: dict[str, Any] = {
    # 5.1 Security and API
    "API_TOKEN": "placeholder-api-token",
    "CORS_ORIGINS": "http://localhost:5173",
    # 5.2 Limits
    "MAX_DOCUMENTS": 10,
    "MAX_FILE_SIZE_MB": 5,
    "ALLOWED_EXTENSIONS": "pdf,docx,txt",
    "INGEST_CHUNK_CHARS": 1000,
    "INGEST_RETRIES": 2,
    "AGENT_MAX_REWRITES": 2,
    "RETRIEVAL_LIMIT": 5,
    "GRAPH_SNAPSHOT_LIMIT": 100,
    "GRAPH_GROUP_ID": "dev-group",
    # 5.3 Storage
    "DATA_DIR": "./data",
    "MYSQL_HOST": "mysql",
    "MYSQL_PORT": 3306,
    "MYSQL_DATABASE": "placeholder_db",
    "MYSQL_USER": "placeholder_user",
    "MYSQL_PASSWORD": "placeholder-mysql-password",
    "MYSQL_ROOT_PASSWORD": "placeholder-mysql-root-password",
    # 5.4 Neo4j
    "NEO4J_URI": "bolt://neo4j:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "placeholder-neo4j-password",
    "NEO4J_DATABASE": "neo4j",
    # 5.5 Extraction and embedding models
    "LLM_BASE_URL": "http://llm.invalid/v1",
    "LLM_API_KEY": "placeholder-llm-key",
    "LLM_MODEL": "placeholder-model",
    "LLM_SMALL_MODEL": "placeholder-small-model",
    "LLM_TEMPERATURE": 0.0,
    "EMBEDDING_BASE_URL": "http://embed.invalid/v1",
    "EMBEDDING_API_KEY": "placeholder-embedding-key",
    "EMBEDDING_MODEL": "placeholder-embedding-model",
    # 5.6 Agent model
    "AGENT_LLM_BASE_URL": "http://agent.invalid/v1",
    "AGENT_LLM_API_KEY": "placeholder-agent-key",
    "AGENT_LLM_MODEL": "placeholder-agent-model",
    "AGENT_LLM_TEMPERATURE": 0.5,
    # 5.7 Langfuse
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

# The four optional LANGFUSE_INIT_* fields. They default to None.
OPTIONAL_FIELDS = (
    "LANGFUSE_INIT_ORG_ID",
    "LANGFUSE_INIT_PROJECT_ID",
    "LANGFUSE_INIT_USER_EMAIL",
    "LANGFUSE_INIT_USER_PASSWORD",
)

# One required field from each plan §5 group, plus the last field of the file.
SAMPLE_REQUIRED_FIELDS = (
    "API_TOKEN",  # 5.1 Security
    "MAX_FILE_SIZE_MB",  # 5.2 Limits
    "GRAPH_GROUP_ID",  # 5.2 Limits (the field that differs between dev and test)
    "MYSQL_ROOT_PASSWORD",  # 5.3 Storage
    "NEO4J_URI",  # 5.4 Neo4j
    "LLM_MODEL",  # 5.5 Extraction and embedding models
    "AGENT_LLM_TEMPERATURE",  # 5.6 Agent model
    "LANGFUSE_SECRET_KEY",  # 5.7 Langfuse
    "MINIO_ROOT_PASSWORD",  # 5.7 Langfuse stack, last field in the file
)


def _env_file_text(values: dict[str, Any], app_env: str | None) -> str:
    lines = [] if app_env is None else [f"APP_ENV={app_env}"]
    lines.extend(f"{key}={value}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def _write_env_file(path: Path, values: dict[str, Any], app_env: str | None) -> Path:
    path.write_text(_env_file_text(values, app_env), encoding="utf-8")
    return path


@pytest.fixture
def process_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Replace os.environ with a copy that starts without APP_ENV."""
    env = dict(os.environ)
    env.pop("APP_ENV", None)
    monkeypatch.setattr(os, "environ", env)
    return env


def _config_module(monkeypatch: pytest.MonkeyPatch, repo_root: Path, name: str) -> types.ModuleType:
    """Execute app/config.py as if it lived at <repo_root>/backend/app/config.py."""
    source = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "\nsettings = load_settings()\n"
    assert source.count(marker) == 1, "app/config.py must end with one module-level load_settings()"
    source = source.replace(marker, "\n")
    module = types.ModuleType(name)
    module.__file__ = str(repo_root / "backend" / "app" / "config.py")
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A fake repo root. Env files for these tests are written here, never in the real repo."""
    root = tmp_path.resolve()
    (root / "backend" / "app").mkdir(parents=True)
    return root


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> types.ModuleType:
    return _config_module(monkeypatch, repo_root, "app_config_under_test")


# --- valid files load ----------------------------------------------------


def test_dev_env_file_loads_every_required_field(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    process_env["APP_ENV"] = "dev"

    settings = config.load_settings()

    assert settings.APP_ENV == "dev"
    for key, expected in VALUES.items():
        assert getattr(settings, key) == expected, key


def test_test_env_file_loads_every_required_field(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env.test", VALUES, app_env="test")
    process_env["APP_ENV"] = "test"

    settings = config.load_settings()

    assert settings.APP_ENV == "test"
    for key, expected in VALUES.items():
        assert getattr(settings, key) == expected, key


def test_load_settings_exports_selected_file_to_process_env(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env.test", VALUES, app_env="test")
    process_env["APP_ENV"] = "test"

    config.load_settings()

    assert process_env["GRAPH_GROUP_ID"] == "dev-group"
    assert process_env["NEO4J_URI"] == "bolt://neo4j:7687"


def test_process_env_value_does_not_override_selected_file(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    # A value exported in the shell is not a settings source, so the file wins.
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    process_env["APP_ENV"] = "dev"
    process_env["GRAPH_GROUP_ID"] = "leaked-from-shell"

    settings = config.load_settings()

    assert settings.GRAPH_GROUP_ID == "dev-group"


# --- missing required fields fail --------------------------------------


@pytest.mark.parametrize("field", SAMPLE_REQUIRED_FIELDS)
def test_missing_required_field_fails_and_names_it(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str], field: str
) -> None:
    values = {key: value for key, value in VALUES.items() if key != field}
    _write_env_file(repo_root / ".env", values, app_env="dev")
    process_env["APP_ENV"] = "dev"

    with pytest.raises(ValidationError) as excinfo:
        config.load_settings()

    assert field in str(excinfo.value)


# --- optional LANGFUSE_INIT_* fields ------------------------------------


def test_file_without_langfuse_init_fields_loads_with_them_none(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    process_env["APP_ENV"] = "dev"

    settings = config.load_settings()

    for key in OPTIONAL_FIELDS:
        assert getattr(settings, key) is None, key


def test_langfuse_init_fields_load_when_present(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    values = dict(VALUES)
    values["LANGFUSE_INIT_ORG_ID"] = "placeholder-org"
    values["LANGFUSE_INIT_PROJECT_ID"] = "placeholder-project"
    values["LANGFUSE_INIT_USER_EMAIL"] = "placeholder@example.invalid"
    values["LANGFUSE_INIT_USER_PASSWORD"] = "placeholder-init-password"
    _write_env_file(repo_root / ".env", values, app_env="dev")
    process_env["APP_ENV"] = "dev"

    settings = config.load_settings()

    assert settings.LANGFUSE_INIT_ORG_ID == "placeholder-org"
    assert settings.LANGFUSE_INIT_USER_PASSWORD == "placeholder-init-password"


# --- APP_ENV selection ---------------------------------------------------


def test_unset_app_env_raises_naming_app_env(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    # process_env has no APP_ENV.

    with pytest.raises(RuntimeError, match="APP_ENV is not set"):
        config.select_env_file()
    with pytest.raises(RuntimeError, match="APP_ENV"):
        config.load_settings()


@pytest.mark.parametrize("bad_value", ["production", "", "Dev"])
def test_invalid_app_env_raises_naming_allowed_values(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str], bad_value: str
) -> None:
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    process_env["APP_ENV"] = bad_value

    with pytest.raises(RuntimeError, match="must be one of: dev, test"):
        config.select_env_file()


# --- dev and test file isolation ----------------------------------------


def test_dev_selects_dot_env_and_reads_only_its_values(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", {**VALUES, "GRAPH_GROUP_ID": "dev-only-group"}, "dev")
    _write_env_file(
        repo_root / ".env.test", {**VALUES, "GRAPH_GROUP_ID": "test-only-group"}, "test"
    )
    process_env["APP_ENV"] = "dev"

    settings = config.load_settings()

    assert config.select_env_file() == repo_root / ".env"
    assert settings.GRAPH_GROUP_ID == "dev-only-group"


def test_test_selects_dot_env_test_and_reads_only_its_values(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", {**VALUES, "GRAPH_GROUP_ID": "dev-only-group"}, "dev")
    _write_env_file(
        repo_root / ".env.test", {**VALUES, "GRAPH_GROUP_ID": "test-only-group"}, "test"
    )
    process_env["APP_ENV"] = "test"

    settings = config.load_settings()

    assert config.select_env_file() == repo_root / ".env.test"
    assert settings.GRAPH_GROUP_ID == "test-only-group"


def test_dev_does_not_fall_back_to_dot_env_test(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env.test", VALUES, app_env="test")
    process_env["APP_ENV"] = "dev"

    with pytest.raises(RuntimeError, match=r"APP_ENV=dev needs .*\.env, which does not exist"):
        config.select_env_file()


def test_test_does_not_fall_back_to_dot_env(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    _write_env_file(repo_root / ".env", VALUES, app_env="dev")
    process_env["APP_ENV"] = "test"

    with pytest.raises(
        RuntimeError, match=r"APP_ENV=test needs .*\.env\.test, which does not exist"
    ):
        config.select_env_file()


# --- file APP_ENV must agree with the process APP_ENV -------------------


def test_file_app_env_mismatch_with_process_raises(
    config: types.ModuleType, repo_root: Path, process_env: dict[str, str]
) -> None:
    # The dev process reads .env, but that file says APP_ENV=test.
    _write_env_file(repo_root / ".env", VALUES, app_env="test")
    process_env["APP_ENV"] = "dev"

    with pytest.raises(
        RuntimeError, match=r"APP_ENV in \.env is 'test' but the process APP_ENV is 'dev'"
    ):
        config.load_settings()
