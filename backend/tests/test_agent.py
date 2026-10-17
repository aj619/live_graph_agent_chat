"""Tests for the agent graph in app.agent (plan §6.8), with fake graph and fake LLM.

app.agent reads settings from app.config at import time, and app.config loads the
selected env file. These tests must never touch the real repo env files, so they
do not import app.agent or app.config at module level. The `agent_module` fixture
builds its own app.config from source under a fake __file__ inside pytest's
tmp_path, with a minimal placeholder .env.test there, then imports app.agent
against that config. The same pattern is used in test_logging.py and test_auth.py.

No test here makes a network call. The LLM is `FakeChatModel`, the graph is
`FakeGraphService`, and every RetrieveResult has empty `episode_uuids_by_edge`, so
`_doc_ids_for_episodes` never reaches a database.

Events are read from the EventBus queue. Each queued item is one SSE block, so the
helper `_drain_events` parses it back into (event type, data).
"""

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
from fakes import FakeChatModel, FakeFailure, FakeGraphService

from app.events import EventBus

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
    # 0 by default so every existing call-count assertion in this file (written
    # before query expansion existed) stays exact. Tests for expansion itself
    # monkeypatch this up, the same way AGENT_MAX_REWRITES tests already do.
    "AGENT_QUERY_EXPANSIONS": 0,
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
def agent_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Yield app.agent, imported against a placeholder app.config built in tmp_path."""
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
    monkeypatch.delitem(sys.modules, "app.agent", raising=False)
    agent = importlib.import_module("app.agent")

    yield agent

    sys.modules.pop("app.agent", None)


def _drain_events(queue: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return every queued SSE block as (event type, parsed data), in arrival order."""
    events: list[tuple[str, dict[str, Any]]] = []
    while not queue.empty():
        block: str = queue.get_nowait()
        event_line, data_line = block.rstrip("\n").split("\n")
        event_type = event_line.removeprefix("event: ")
        events.append((event_type, json.loads(data_line.removeprefix("data: "))))
    return events


# ---------------------------------------------------------------------------
# 1. chat.sources is published before the first chat.token
# ---------------------------------------------------------------------------


async def test_answer_publishes_sources_before_first_token(agent_module: ModuleType) -> None:
    fake_llm = FakeChatModel(stream_tokens=["Hello", " world"])
    bus = EventBus()
    queue = bus.subscribe()
    retrieved = agent_module.RetrieveResult(
        facts=["fact one"],
        node_ids=["n1"],
        edge_ids=["e1"],
        node_names={"n1": "Node One"},
    )
    state = {
        "chat_id": "chat-1",
        "question": "what is fact one?",
        "query": "what is fact one?",
        "rewrites": 0,
        "retrieved": retrieved,
        "grounded": True,
    }

    answer = agent_module.make_answer_node(fake_llm, bus)
    await answer(state)

    events = _drain_events(queue)
    assert [event_type for event_type, _ in events] == [
        "chat.sources",
        "chat.token",
        "chat.token",
    ]
    sources = events[0][1]
    assert sources == {
        "chat_id": "chat-1",
        "node_ids": ["n1"],
        "edge_ids": ["e1"],
        "doc_ids": [],
        "nodes": [{"id": "n1", "name": "Node One"}],
        "facts": ["fact one"],
    }
    assert [data["token"] for _, data in events[1:]] == ["Hello", " world"]
    assert all(data["chat_id"] == "chat-1" for _, data in events[1:])
    assert len(fake_llm.stream_calls) == 1


async def test_answer_with_no_retrieved_result_publishes_empty_sources(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(stream_tokens=["Sorry"])
    bus = EventBus()
    queue = bus.subscribe()
    state = {
        "chat_id": "chat-2",
        "question": "anything?",
        "query": "anything?",
        "rewrites": 2,
        "retrieved": None,
        "grounded": False,
    }

    await agent_module.make_answer_node(fake_llm, bus)(state)

    events = _drain_events(queue)
    assert events[0][0] == "chat.sources"
    assert events[0][1]["node_ids"] == []
    assert events[0][1]["facts"] == []
    assert events[0][1]["doc_ids"] == []
    assert [event_type for event_type, _ in events] == ["chat.sources", "chat.token"]


# ---------------------------------------------------------------------------
# 2. The rewrite loop stops at AGENT_MAX_REWRITES
# ---------------------------------------------------------------------------


async def test_rewrite_loop_stops_at_agent_max_rewrites(
    agent_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_module.settings, "AGENT_MAX_REWRITES", 2)
    fake_graph = FakeGraphService(retrieve_result=agent_module.RetrieveResult(facts=["a fact"]))
    fake_llm = FakeChatModel(invoke_reply="NO", stream_tokens=["answer"])
    bus = EventBus()
    compiled = agent_module.build_agent_graph(fake_graph, fake_llm, bus)
    initial_state = {
        "chat_id": "chat-3",
        "question": "unanswerable?",
        "query": "unanswerable?",
        "rewrites": 0,
        "retrieved": None,
        "grounded": False,
    }

    final = await compiled.ainvoke(initial_state)

    # Trace with max_rewrites = 2, every grade answers NO:
    #   retrieve #1 -> grade (ainvoke #1, NO) -> rewrite (ainvoke #2, rewrites=1)
    #   -> retrieve #2 -> grade (ainvoke #3, NO) -> rewrite (ainvoke #4, rewrites=2)
    #   -> retrieve #3 -> grade (ainvoke #5, NO) -> route sees rewrites>=2 -> answer
    #   -> answer runs astream once -> END.
    assert final["rewrites"] == 2
    assert final["grounded"] is False
    assert len(fake_graph.retrieve_queries) == 3
    assert len(fake_llm.invoke_calls) == 5
    assert len(fake_llm.stream_calls) == 1


# ---------------------------------------------------------------------------
# 3. A failure in run() publishes chat.error and never raises
# ---------------------------------------------------------------------------


async def test_run_failure_publishes_generic_chat_error_and_logs_traceback(
    agent_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_llm = FakeChatModel()
    monkeypatch.setattr(agent_module, "build_agent_llm", lambda cfg=None: fake_llm)
    fake_graph = FakeGraphService(fail_on={"retrieve": 1})
    bus = EventBus()
    queue = bus.subscribe()
    caplog.set_level(logging.ERROR)

    # No exception may escape run(); reaching the assertions below proves that.
    await agent_module.run("chat-4", "a question", fake_graph, bus)

    events = _drain_events(queue)
    assert events == [
        ("chat.error", {"chat_id": "chat-4", "message": agent_module.AGENT_ERROR_MESSAGE})
    ]
    assert all(event_type != "chat.done" for event_type, _ in events)

    error_records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert error_records, "run() must log the failure at ERROR level"
    exc_info = error_records[0].exc_info
    assert exc_info is not None
    assert isinstance(exc_info[1], FakeFailure)


# ---------------------------------------------------------------------------
# 4. A successful run() publishes chat.done and no chat.error
# ---------------------------------------------------------------------------


async def test_run_success_publishes_sources_tokens_then_done(
    agent_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm = FakeChatModel(invoke_reply="YES", stream_tokens=["Hi", "!"])
    monkeypatch.setattr(agent_module, "build_agent_llm", lambda cfg=None: fake_llm)
    fake_graph = FakeGraphService(retrieve_result=agent_module.RetrieveResult(facts=["a fact"]))
    bus = EventBus()
    queue = bus.subscribe()

    await agent_module.run("chat-5", "a question", fake_graph, bus)

    events = _drain_events(queue)
    event_types = [event_type for event_type, _ in events]
    assert event_types == ["chat.sources", "chat.token", "chat.token", "chat.done"]
    assert "chat.error" not in event_types
    assert [data["token"] for _, data in events[1:3]] == ["Hi", "!"]
    assert events[-1] == ("chat.done", {"chat_id": "chat-5"})


# ---------------------------------------------------------------------------
# 5. parse_verdict: pure function cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("YES, that works", True),
        ("NO, not enough", False),
        ("yes", True),
        ("No.", False),
        ("I'm not sure", False),
        ("", False),
        ("NO, the facts say nothing. YES would be wrong.", False),
        ("Maybe. YES, because of the fact.", True),
        ("Nothing here, but YES", True),
    ],
)
def test_parse_verdict_reads_first_yes_or_no_word(
    agent_module: ModuleType, text: str, expected: bool
) -> None:
    assert agent_module.parse_verdict(text) is expected


# ---------------------------------------------------------------------------
# 6. Grade with no facts never calls the LLM
# ---------------------------------------------------------------------------


async def test_grade_with_no_facts_is_false_and_makes_no_llm_call(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(invoke_reply="YES")
    grade = agent_module.make_grade_node(fake_llm)
    state = {
        "chat_id": "chat-6",
        "question": "anything?",
        "query": "anything?",
        "rewrites": 0,
        "retrieved": agent_module.RetrieveResult(facts=[]),
        "grounded": True,
    }

    result = await grade(state)

    assert result["grounded"] is False
    assert fake_llm.invoke_calls == []


async def test_grade_with_none_retrieved_is_false_and_makes_no_llm_call(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(invoke_reply="YES")
    grade = agent_module.make_grade_node(fake_llm)
    state = {
        "chat_id": "chat-7",
        "question": "anything?",
        "query": "anything?",
        "rewrites": 0,
        "retrieved": None,
        "grounded": True,
    }

    result = await grade(state)

    assert result["grounded"] is False
    assert fake_llm.invoke_calls == []


# ---------------------------------------------------------------------------
# 7. expand_query: pure parsing of the LLM's variant list
# ---------------------------------------------------------------------------


async def test_expand_query_parses_lines_dedupes_and_caps_to_limit(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(
        invoke_reply=(
            "variant one\n\nvariant one\nOriginal Question\nvariant two\nvariant three"
        )
    )

    variants = await agent_module.expand_query(fake_llm, "Original Question", 2)

    assert variants == ["variant one", "variant two"]
    assert len(fake_llm.invoke_calls) == 1


async def test_expand_query_with_zero_limit_skips_the_llm_call(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(invoke_reply="should never be seen")

    variants = await agent_module.expand_query(fake_llm, "a question", 0)

    assert variants == []
    assert fake_llm.invoke_calls == []


async def test_expand_query_with_only_duplicate_lines_returns_empty(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(invoke_reply="A question\n\nA QUESTION")

    variants = await agent_module.expand_query(fake_llm, "A question", 3)

    assert variants == []


# ---------------------------------------------------------------------------
# 8. The retrieve node expands the query and merges results from every variant
# ---------------------------------------------------------------------------


async def test_retrieve_node_expands_query_and_merges_results(
    agent_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_module.settings, "AGENT_QUERY_EXPANSIONS", 2)
    fake_llm = FakeChatModel(invoke_reply="variant one\nvariant two")
    fake_graph = FakeGraphService(
        retrieve_results_by_query={
            "original question": agent_module.RetrieveResult(
                node_ids=["n1"],
                edge_ids=["e1"],
                facts=["fact one"],
                node_names={"n1": "Node One"},
            ),
            "variant one": agent_module.RetrieveResult(
                node_ids=["n1", "n2"],
                edge_ids=["e1", "e2"],
                facts=["fact one", "fact two"],
                node_names={"n1": "Node One", "n2": "Node Two"},
            ),
            "variant two": agent_module.RetrieveResult(),
        }
    )
    retrieve = agent_module.make_retrieve_node(fake_graph, fake_llm)
    state = {
        "chat_id": "chat-8",
        "question": "original question",
        "query": "original question",
        "rewrites": 0,
        "retrieved": None,
        "grounded": False,
    }

    result = await retrieve(state)

    assert fake_graph.retrieve_queries == ["original question", "variant one", "variant two"]
    merged = result["retrieved"]
    assert merged.node_ids == ["n1", "n2"]
    assert merged.edge_ids == ["e1", "e2"]
    assert merged.facts == ["fact one", "fact two"]
    assert merged.node_names == {"n1": "Node One", "n2": "Node Two"}


async def test_retrieve_node_with_expansions_disabled_calls_retrieve_once(
    agent_module: ModuleType,
) -> None:
    fake_llm = FakeChatModel(invoke_reply="should never be seen")
    fake_graph = FakeGraphService(retrieve_result=agent_module.RetrieveResult(facts=["a fact"]))
    retrieve = agent_module.make_retrieve_node(fake_graph, fake_llm)
    state = {
        "chat_id": "chat-9",
        "question": "a question",
        "query": "a question",
        "rewrites": 0,
        "retrieved": None,
        "grounded": False,
    }

    result = await retrieve(state)

    assert fake_graph.retrieve_queries == ["a question"]
    assert fake_llm.invoke_calls == []
    assert result["retrieved"].facts == ["a fact"]
