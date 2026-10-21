"""Integration test for the graph service against real Neo4j (plan §6.6, T3.2).

The test inserts one fixture episode through GraphService with fake model
clients, retrieves, takes a snapshot, removes the episode, and closes the
service. It is marked `integration` and uses the real neo4j driver and the
real Graphiti client. No model endpoint is called: the three clients are the
fakes defined in this file, which never make a network request.

Settings: when the process APP_ENV is already `test`, the driver has set up the
test stack, so the real app.config is used as it is. The conftest guard checks
its values. Otherwise this module installs a placeholder `.env.test` in a temp
directory. It points NEO4J_URI at bolt://127.0.0.1:17687, where nothing listens
on a dev box, so the connection is refused at once. The module-scoped autouse
fixture below runs before conftest's function-scoped guard, so the guard sees
test-shaped settings. The real repo env files are never read, and the patched
modules and environment are restored when the module finishes.

Connectivity: the test first calls GraphService.start(), which needs a reachable
Neo4j. If the connection is refused, the test skips with "not verified: Neo4j
not reachable". A skip is reported as not verified, never as passed.

Fake model clients: the fake LLM client answers each structured request with
the emptiest valid instance of the requested response model. Graphiti therefore
extracts no entities or edges from the fixture text. This is a best-effort fake.
It has not been run against a live extraction pipeline in the environment that
wrote it, so the test asserts the types returned and the absence of errors, not
specific extracted facts.
"""

import importlib
import os
import sys
import types
import typing
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, ModelSize
from graphiti_core.prompts.models import Message
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"
_PATCHED_MODULES = ("app.config", "app.models", "app.graph")
EMBEDDING_DIMENSIONS = 768

# Placeholder values for every required field in plan §5. None is a real secret.
# NEO4J_URI points at a port with no listener, so a run without a test stack is
# refused quickly and skips as not verified.
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
    "NEO4J_URI": "bolt://127.0.0.1:17687",
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
def _graph_test_settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Install test-shaped settings for this module, before conftest's function-scoped guard.

    A module-scoped fixture is set up before any function-scoped fixture, so the
    conftest guard always sees the settings installed here.
    """
    if os.environ.get("APP_ENV") == "test":
        # The driver has set up the test stack. Use the real .env.test settings.
        yield
        return

    env_dir = tmp_path_factory.mktemp("graph_env")
    env_text = "\n".join(f"{key}={value}" for key, value in ENV_VALUES.items()) + "\n"
    (env_dir / ".env.test").write_text(env_text, encoding="utf-8")

    saved_environ = dict(os.environ)
    saved_modules = {name: sys.modules.get(name) for name in _PATCHED_MODULES}
    app_package = importlib.import_module("app")
    saved_attrs = {name: getattr(app_package, name, None) for name in ("config", "models", "graph")}
    try:
        os.environ["APP_ENV"] = "test"
        config = _build_test_config(env_dir)
        sys.modules["app.config"] = config
        app_package.__dict__["config"] = config
        for name in ("app.models", "app.graph"):
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


def _empty_value(annotation: Any) -> Any:
    """Return the emptiest value that satisfies a field annotation.

    This is the generic response-model builder used by FakeLLMClient. Rules, in order:
    - list[...] or list -> []; dict[...] or dict -> {}.
    - str -> "", bool -> False, int -> 0, float -> 0.0.
    - Optional[X] / X | None -> None (the field may be null).
    - Literal[...] -> its first value (a valid enum choice).
    - A BaseModel subclass -> an empty instance of it, built recursively from its
      required fields.
    - Anything else -> None. Pydantic validation in the caller reports the field if
      None is not allowed there.
    The result is checked by model_validate() in FakeLLMClient, so a rule that does
    not fit a real Graphiti response model fails loudly rather than silently.
    """
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return args[0]
    if origin is typing.Union or origin is types.UnionType:
        if type(None) in args:
            return None
        return _empty_value(args[0])
    if origin is list or annotation is list:
        return []
    if origin is dict or annotation is dict:
        return {}
    if annotation is str:
        return ""
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _empty_model(annotation)
    return None


def _empty_model(model: type[BaseModel]) -> BaseModel:
    """Build an instance of a response model from its required fields only."""
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if field.is_required():
            values[name] = _empty_value(field.annotation)
    return model.model_validate(values)


class FakeLLMClient(LLMClient):
    """A fake Graphiti LLM client. It makes no network request.

    It subclasses graphiti_core's LLMClient, so Graphiti accepts it. Each structured
    call returns the emptiest valid instance of the requested response model, so
    extraction finds nothing and the episode is stored as a plain episodic node.
    """

    def __init__(self) -> None:
        super().__init__(config=None, cache=False)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        if response_model is None:
            return {}
        return _empty_model(response_model).model_dump()


class FakeEmbedder(EmbedderClient):
    """A fake Graphiti embedder. It returns a fixed vector and makes no network request."""

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        return [0.0] * EMBEDDING_DIMENSIONS

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in input_data_list]


class FakeReranker(CrossEncoderClient):
    """A fake Graphiti cross-encoder. It keeps the passages in order with score 1.0."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 1.0) for passage in passages]


async def _probe_neo4j(cfg: Any) -> None:
    """Skip as not verified unless a Neo4j server answers at NEO4J_URI.

    A single verify_connectivity() call on a bare driver fails at once when nothing
    listens. GraphService.start() is not used as the probe, because the Graphiti
    query path retries a refused connection for about 30 seconds before it fails.
    """
    probe = AsyncGraphDatabase.driver(cfg.NEO4J_URI, auth=(cfg.NEO4J_USER, cfg.NEO4J_PASSWORD))
    try:
        await probe.verify_connectivity()
    except ServiceUnavailable as exc:
        pytest.skip(f"not verified: Neo4j not reachable at {cfg.NEO4J_URI} ({exc})")
    finally:
        await probe.close()


@pytest.mark.integration
async def test_graph_episode_round_trips_through_real_neo4j() -> None:
    """Insert one episode, retrieve, snapshot, remove, and close, against real Neo4j."""
    config_module = importlib.import_module("app.config")
    graph_module = importlib.import_module("app.graph")
    models_module = importlib.import_module("app.models")
    cfg = config_module.settings

    models = models_module.ModelClients(
        llm_client=FakeLLMClient(),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
    )
    await _probe_neo4j(cfg)
    graph = graph_module.GraphService(cfg=cfg, models=models)
    episode_uuid = str(uuid.uuid4())
    try:
        await graph.start()

        await graph.insert_episode(
            episode_uuid=episode_uuid,
            name="fixture episode",
            body="Alice works at Acme Corp.",
            source_description="integration test fixture",
        )

        retrieved = await graph.retrieve("Alice")
        assert isinstance(retrieved, graph_module.RetrieveResult)

        snapshot = await graph.snapshot()
        assert isinstance(snapshot, graph_module.GraphSnapshot)

        await graph.remove_episode(episode_uuid)
    finally:
        await graph.close()
