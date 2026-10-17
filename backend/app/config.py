"""Runtime configuration for the backend (plan §5).

Settings read exactly one env file, chosen by APP_ENV:

- APP_ENV=dev  reads <repo>/.env       and never reads .env.test
- APP_ENV=test reads <repo>/.env.test  and never reads .env

There is no fallback between the two files. A missing value fails at startup
with an error naming the variable. Process environment variables other than
APP_ENV are not read, so a dev value exported in the shell cannot leak into a
test run.

After loading, every variable in the selected file is exported to os.environ,
because the Langfuse SDK reads some of its configuration from the process
environment.
"""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Maps each APP_ENV value to the single env file it reads. Keys are the
# allowed APP_ENV values; this mapping is the only place the file names live.
ENV_FILE_BY_APP_ENV: dict[str, str] = {
    "dev": ".env",
    "test": ".env.test",
}


def select_env_file() -> Path:
    """Return the one env file that matches the APP_ENV process variable.

    The directory searched is REPO_ROOT by default, correct for a local
    checkout where this file sits three levels under the repo root. A
    container loses that nesting (backend/Dockerfile copies app/ straight
    into /app, dropping the backend/ prefix), so ENV_FILE_DIR lets the
    compose fragment that bind-mounts the real file point at it explicitly.
    """
    if "APP_ENV" not in os.environ:
        raise RuntimeError(
            "APP_ENV is not set. Export APP_ENV=dev or APP_ENV=test to choose the env file."
        )
    app_env = os.environ["APP_ENV"]
    file_name = ENV_FILE_BY_APP_ENV.get(app_env)
    if file_name is None:
        allowed = ", ".join(sorted(ENV_FILE_BY_APP_ENV))
        raise RuntimeError(f"APP_ENV must be one of: {allowed}. Got {app_env!r}.")
    root = Path(os.environ["ENV_FILE_DIR"]) if "ENV_FILE_DIR" in os.environ else REPO_ROOT
    path = root / file_name
    if not path.is_file():
        raise RuntimeError(f"APP_ENV={app_env} needs {path}, which does not exist.")
    return path


class Settings(BaseSettings):
    """Every variable in the plan §5 contract. No field has a default unless it is optional."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # env_settings is dropped on purpose: values come only from the selected file.
        selected = DotEnvSettingsSource(settings_cls, env_file=select_env_file())
        return (init_settings, selected)

    # 5.1 Security and API
    APP_ENV: Literal["dev", "test"]
    API_TOKEN: str
    CORS_ORIGINS: str

    # 5.2 Limits
    MAX_DOCUMENTS: int
    MAX_FILE_SIZE_MB: int
    ALLOWED_EXTENSIONS: str
    INGEST_CHUNK_CHARS: int
    INGEST_RETRIES: int
    AGENT_MAX_REWRITES: int
    AGENT_QUERY_EXPANSIONS: int
    RETRIEVAL_LIMIT: int
    GRAPH_SNAPSHOT_LIMIT: int
    GRAPH_GROUP_ID: str

    # 5.3 Storage
    DATA_DIR: str
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_DATABASE: str
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    # Read by compose/mysql.yml's own MySQL container at first start (bootstrap and
    # healthcheck). The app itself never uses it. Optional: irrelevant when MYSQL_HOST
    # points at an externally managed MySQL instance instead of that compose fragment.
    MYSQL_ROOT_PASSWORD: str | None = None

    # 5.4 Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    NEO4J_DATABASE: str

    # 5.5 Extraction and embedding models
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str
    LLM_SMALL_MODEL: str
    LLM_TEMPERATURE: float
    EMBEDDING_BASE_URL: str
    EMBEDDING_API_KEY: str
    EMBEDDING_MODEL: str

    # 5.6 Agent model
    AGENT_LLM_BASE_URL: str
    AGENT_LLM_API_KEY: str
    AGENT_LLM_MODEL: str
    AGENT_LLM_TEMPERATURE: float

    # 5.7 Langfuse
    LANGFUSE_ENABLED: bool
    LANGFUSE_HOST: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_SECRET_KEY: str
    NEXTAUTH_SECRET: str
    NEXTAUTH_URL: str
    SALT: str
    ENCRYPTION_KEY: str
    # Optional bootstrap values. Unset means skip.
    LANGFUSE_INIT_ORG_ID: str | None = None
    LANGFUSE_INIT_PROJECT_ID: str | None = None
    LANGFUSE_INIT_USER_EMAIL: str | None = None
    LANGFUSE_INIT_USER_PASSWORD: str | None = None
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_VERSION: str
    CLICKHOUSE_USER: str
    CLICKHOUSE_PASSWORD: str
    REDIS_AUTH: str
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str

    # 5.8 VITE_APP_TITLE is read only by the frontend build, so it is not a field here.


def load_settings() -> Settings:
    """Load Settings from the selected file, check APP_ENV matches, and export to os.environ."""
    path = select_env_file()
    # Required fields are filled from the env file, which mypy cannot see.
    settings = Settings()  # type: ignore[call-arg]
    if settings.APP_ENV != os.environ["APP_ENV"]:
        raise RuntimeError(
            f"APP_ENV in {path.name} is {settings.APP_ENV!r} but the process APP_ENV is "
            f"{os.environ['APP_ENV']!r}. Fix the file or the environment."
        )
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ[key] = value
    return settings


settings = load_settings()
