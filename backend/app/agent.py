"""Agent state, agent LLM factory, and the retrieve and grade nodes (plan §6.8).

This module holds the first pieces of the LangGraph agent. The rewrite and
answer nodes, the conditional routing, and the compiled graph are added by
later tasks in this same file.

State (`AgentState`, a TypedDict):
- chat_id: str. The chat the question belongs to.
- question: str. The user's original question. Never changed by the agent.
- query: str. The current search query used by `retrieve`. Starts equal to
  `question`. A later `rewrite` node may replace it.
- rewrites: int. How many rewrite attempts have run so far. Starts at 0.
- retrieved: RetrieveResult | None. The last result from `GraphService.retrieve`.
  None until the first retrieve runs.
- grounded: bool. The grade node's verdict. Starts False.

Node wiring: each node that needs a dependency is built by a factory and
returned as a closure with the LangGraph node signature
`async (AgentState) -> AgentState`. The caller passes the dependency in:
- `make_retrieve_node(graph)` takes a `GraphService`. The shared instance is
  owned by the caller (T2.29), not built here.
- `make_grade_node(llm)` takes an agent LLM, typically from `build_agent_llm()`.

Each node returns a full new state dict. It does not mutate the input.

Agent LLM: `build_agent_llm(cfg)` builds a `ChatOpenAI` from the AGENT_LLM_*
settings. It only stores the base URL and key. No network call happens until
the model is invoked. Tests pass a fake object with an async `ainvoke` in place
of the real client.

Tracing: every LLM call passes `get_callback_handlers()` in its config. That
returns the Langfuse handler only when LANGFUSE_ENABLED is true.

Grade parsing: the model's reply is scanned for the words YES and NO, case
insensitively. The first one found decides the verdict. A reply with neither
word counts as NO. A reply with no facts is NO and makes no model call.
"""

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy import select

from app.config import Settings, settings
from app.db import SessionLocal
from app.events import EventBus
from app.graph import GraphService, RetrieveResult
from app.registry import InsertionChunk
from app.tracing import get_callback_handlers

_VERDICT_PATTERN = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)


class AgentState(TypedDict):
    """The state passed between agent nodes. See the module docstring for each field."""

    chat_id: str
    question: str
    query: str
    rewrites: int
    retrieved: RetrieveResult | None
    grounded: bool


def build_agent_llm(cfg: Settings = settings) -> ChatOpenAI:
    """Return the agent's chat model, built from the AGENT_LLM_* settings.

    Args:
        cfg: The settings to build from. Defaults to the module-level `settings`.
    """
    return ChatOpenAI(
        base_url=cfg.AGENT_LLM_BASE_URL,
        api_key=SecretStr(cfg.AGENT_LLM_API_KEY),
        model=cfg.AGENT_LLM_MODEL,
        temperature=cfg.AGENT_LLM_TEMPERATURE,
    )


def make_retrieve_node(graph: GraphService) -> Callable[[AgentState], Awaitable[AgentState]]:
    """Return the retrieve node, which runs a graph search for the state's `query`.

    Args:
        graph: The service whose `retrieve` runs the hybrid search.
    """

    async def retrieve(state: AgentState) -> AgentState:
        result = await graph.retrieve(state["query"])
        return {**state, "retrieved": result}

    return retrieve


def _grade_prompt(question: str, facts: list[str]) -> str:
    """Build the grading prompt from the question and the retrieved facts."""
    fact_lines = "\n".join(f"- {fact}" for fact in facts)
    return (
        f"Given these facts:\n{fact_lines}\n\n"
        "Can you answer this question using only these facts?\n"
        f"Question: {question}\n\n"
        "Answer YES or NO."
    )


def parse_verdict(text: str) -> bool:
    """Return True only when the first YES or NO word in `text` is YES.

    Text with neither word returns False, the safe default.
    """
    match = _VERDICT_PATTERN.search(text)
    return match is not None and match.group(1).upper() == "YES"


def make_grade_node(llm: ChatOpenAI) -> Callable[[AgentState], Awaitable[AgentState]]:
    """Return the grade node, which sets `grounded` from the facts and the agent LLM.

    With no facts, `grounded` is False and the LLM is not called.

    Args:
        llm: The agent chat model. Only its async `ainvoke` is used.
    """

    async def grade(state: AgentState) -> AgentState:
        retrieved = state["retrieved"]
        facts = retrieved.facts if retrieved is not None else []
        if not facts:
            return {**state, "grounded": False}
        response = await llm.ainvoke(
            _grade_prompt(state["question"], facts),
            config={"callbacks": get_callback_handlers()},
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        return {**state, "grounded": parse_verdict(content)}

    return grade


def _rewrite_prompt(question: str, query: str) -> str:
    """Build the rewrite prompt from the question and the query that found too little."""
    return (
        f"The search query '{query}' for the question '{question}' did not return "
        "enough facts to answer it. Suggest a short, different search query (a few "
        "words) that might find better results. Reply with only the new query, "
        "nothing else."
    )


def make_rewrite_node(llm: ChatOpenAI) -> Callable[[AgentState], Awaitable[AgentState]]:
    """Return the rewrite node, which asks the agent LLM for a new search query.

    The reply is stripped of whitespace and used as the new `query`. If the reply
    is empty after stripping, `query` falls back to the original `question`, the
    safe default. `rewrites` goes up by one. `retrieved` and `grounded` are not
    touched here. The next retrieve and grade passes recompute them.

    Args:
        llm: The agent chat model. Only its async `ainvoke` is used.
    """

    async def rewrite(state: AgentState) -> AgentState:
        response = await llm.ainvoke(
            _rewrite_prompt(state["question"], state["query"]),
            config={"callbacks": get_callback_handlers()},
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        new_query = content.strip() or state["question"]
        return {**state, "query": new_query, "rewrites": state["rewrites"] + 1}

    return rewrite


def route_after_grade(state: AgentState) -> Literal["answer", "rewrite"]:
    """Return the next node after grade: "answer" or "rewrite".

    Returns "answer" when `grounded` is True, or when `rewrites` has reached
    `AGENT_MAX_REWRITES`. The limit check is what stops the rewrite to retrieve
    loop. Otherwise returns "rewrite". This is a pure decision with no LLM call.
    The graph wiring that uses it is added in a later task.
    """
    if state["grounded"] or state["rewrites"] >= settings.AGENT_MAX_REWRITES:
        return "answer"
    return "rewrite"


def _doc_ids_for_episodes(episode_uuids: set[uuid.UUID]) -> list[str]:
    """Return the distinct document IDs (as strings) that own the given episode UUIDs.

    Runs a blocking SQLAlchemy query, so the caller runs it in a worker thread.
    An empty set returns [] without a query, because an empty IN clause is invalid.
    """
    if not episode_uuids:
        return []
    stmt = (
        select(InsertionChunk.doc_id)
        .where(InsertionChunk.episode_uuid.in_(list(episode_uuids)))
        .distinct()
    )
    with SessionLocal() as session:
        doc_ids = session.scalars(stmt).all()
    return sorted({str(doc_id) for doc_id in doc_ids})


def _answer_prompt(question: str, facts: list[str]) -> str:
    """Build the answer prompt. It restricts the model to the supplied facts."""
    fact_lines = "\n".join(f"- {fact}" for fact in facts) if facts else "(no facts available)"
    return (
        "Answer the question using only the facts below. If the facts are not enough "
        "to answer, say so clearly instead of guessing.\n\n"
        f"Facts:\n{fact_lines}\n\n"
        f"Question: {question}"
    )


def make_answer_node(
    llm: ChatOpenAI, bus: EventBus
) -> Callable[[AgentState], Awaitable[AgentState]]:
    """Return the answer node, which publishes the sources and then streams the answer.

    Order is fixed. First it publishes `chat.sources` built from `retrieved`, with
    the node IDs, edge IDs, facts, node names, and the de-duplicated document IDs
    that own the episodes behind the edges. Only after that does it stream the
    model's answer, publishing one `chat.token` per non-empty text chunk. A None
    `retrieved` is treated as an empty result.

    Args:
        llm: The agent chat model. Only its async `astream` is used.
        bus: The event bus that carries the `chat.sources` and `chat.token` events.
    """

    async def answer(state: AgentState) -> AgentState:
        retrieved = state["retrieved"] or RetrieveResult()
        chat_id = state["chat_id"]

        episode_uuids = {
            uuid.UUID(episode)
            for episodes in retrieved.episode_uuids_by_edge.values()
            for episode in episodes
        }
        doc_ids = await asyncio.to_thread(_doc_ids_for_episodes, episode_uuids)
        nodes = [
            {"id": node_id, "name": retrieved.node_names.get(node_id, "")}
            for node_id in retrieved.node_ids
        ]
        bus.publish(
            "chat.sources",
            {
                "chat_id": chat_id,
                "node_ids": retrieved.node_ids,
                "edge_ids": retrieved.edge_ids,
                "doc_ids": doc_ids,
                "nodes": nodes,
                "facts": retrieved.facts,
            },
        )

        async for chunk in llm.astream(
            _answer_prompt(state["question"], retrieved.facts),
            config={"callbacks": get_callback_handlers()},
        ):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                bus.publish("chat.token", {"chat_id": chat_id, "token": text})

        return {**state}

    return answer
