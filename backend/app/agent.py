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
- `make_retrieve_node(graph, llm)` takes a `GraphService` (shared instance,
  owned by the caller, T2.29) and the agent LLM. It expands the query into
  AGENT_QUERY_EXPANSIONS variants (rephrasings plus a HyDE-style hypothetical
  passage, see `expand_query`), runs `graph.retrieve` for the original query and
  every variant concurrently, and merges the results.
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
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr
from sqlalchemy import select

from app.call_logging import log_call, start_chat_log, timed
from app.config import Settings, settings
from app.db import SessionLocal
from app.events import EventBus
from app.graph import GraphService, RetrieveResult, merge_retrieve_results
from app.registry import InsertionChunk
from app.tracing import get_callback_handlers

logger = logging.getLogger(__name__)

_VERDICT_PATTERN = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)

AGENT_ERROR_MESSAGE = "The assistant could not answer this question."
"""Generic client-facing text for chat.error. Details go to the logs only."""


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


def _expand_query_prompt(question: str, limit: int) -> str:
    """Build the prompt asking the agent LLM for alternative search strings."""
    return (
        "A search system needs to find facts in a document that answer this "
        f"question:\n{question}\n\n"
        f"Write {limit} alternative search queries that might find the same facts, "
        "each on its own line, nothing else. Phrase at least one of them as a short "
        "factual statement that could appear in the document itself, not as a "
        "question — for example, if the question asks about a ratio, phrase one line "
        "as a plausible statement of that ratio. Do not number the lines or add any "
        "other text."
    )


async def expand_query(llm: ChatOpenAI, question: str, limit: int) -> list[str]:
    """Return up to `limit` alternative search strings for `question`, or [] for none.

    A mix of rephrasings and at least one hypothetical-passage-style line (the
    HyDE technique): phrasing one variant as a statement rather than a question
    often matches the source text's own wording better than the question does.
    Lines identical to the question (case-insensitive) or empty after stripping
    are dropped, as are duplicates. `limit <= 0` skips the LLM call and returns
    [], so the caller falls back to searching with only the original query.

    Args:
        llm: The agent chat model. Only its async `ainvoke` is used.
        question: The question to generate search-query variants for.
        limit: The maximum number of variants to return.
    """
    if limit <= 0:
        return []
    response = await timed(
        "agent_llm_expand_query",
        llm.ainvoke(
            _expand_query_prompt(question, limit),
            config={"callbacks": get_callback_handlers()},
        ),
    )
    content = response.content if isinstance(response.content, str) else str(response.content)
    seen = {question.strip().lower()}
    variants: list[str] = []
    for line in content.splitlines():
        candidate = line.strip()
        if not candidate or candidate.lower() in seen:
            continue
        seen.add(candidate.lower())
        variants.append(candidate)
        if len(variants) >= limit:
            break
    return variants


def make_retrieve_node(
    graph: GraphService, llm: ChatOpenAI
) -> Callable[[AgentState], Awaitable[AgentState]]:
    """Return the retrieve node: expands the query, searches for each variant, merges.

    Runs `expand_query` once (AGENT_QUERY_EXPANSIONS variants, or none when that
    setting is 0), then runs `graph.retrieve` for the original query and every
    variant concurrently, and merges the results with `merge_retrieve_results`.
    Every `retrieve` call does Neo4j-local work plus a local reranking model
    (see app/graph.py and app/models.py) — no provider API calls — so running
    several concurrently carries no rate-limit risk; only the one expansion LLM
    call above has that cost.

    Args:
        graph: The service whose `retrieve` runs the hybrid search.
        llm: The agent chat model used to generate query variants.
    """

    async def retrieve(state: AgentState) -> AgentState:
        query = state["query"]
        variants = await expand_query(llm, query, settings.AGENT_QUERY_EXPANSIONS)
        if not variants:
            # No expansion (disabled, or the LLM returned nothing usable): skip
            # merge_retrieve_results entirely, not just as an optimization. It
            # enforces facts/edge_ids being parallel lists (the dataclass's own
            # documented invariant), which a single real GraphService.retrieve
            # result always satisfies — merging is only needed, and only safe to
            # assume that invariant for, once there is more than one result.
            return {**state, "retrieved": await graph.retrieve(query)}
        results = await asyncio.gather(*(graph.retrieve(q) for q in (query, *variants)))
        return {**state, "retrieved": merge_retrieve_results(list(results))}

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
        response = await timed(
            "agent_llm_grade",
            llm.ainvoke(
                _grade_prompt(state["question"], facts),
                config={"callbacks": get_callback_handlers()},
            ),
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
        response = await timed(
            "agent_llm_rewrite",
            llm.ainvoke(
                _rewrite_prompt(state["question"], state["query"]),
                config={"callbacks": get_callback_handlers()},
            ),
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

        start = time.monotonic()
        try:
            async for chunk in llm.astream(
                _answer_prompt(state["question"], retrieved.facts),
                config={"callbacks": get_callback_handlers()},
            ):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    bus.publish("chat.token", {"chat_id": chat_id, "token": text})
        finally:
            log_call("agent_llm_answer", time.monotonic() - start)

        return {**state}

    return answer


def _as_graph_node(
    node: Callable[[AgentState], Awaitable[AgentState]],
) -> Callable[..., Awaitable[AgentState]]:
    """Return `node` typed for `StateGraph.add_node`.

    The node factories return `Callable[[AgentState], ...]`. Mypy reads that as
    positional-only, which LangGraph's node protocol does not accept. The value
    is returned unchanged, so runtime behaviour is the same.
    """
    return node


def build_agent_graph(
    graph: GraphService, llm: ChatOpenAI, bus: EventBus
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Build and compile the agent graph for one run (plan §6.8).

    Wiring: START -> retrieve -> grade. grade goes to answer or rewrite by
    `route_after_grade`. rewrite goes back to retrieve, which is the loop. answer
    goes to END. The graph is built fresh for each run, so its nodes are bound to
    this run's `graph`, `llm`, and `bus`.

    Args:
        graph: The service the retrieve node searches with.
        llm: The agent chat model used by the grade, rewrite, and answer nodes.
        bus: The event bus the answer node publishes to.
    """
    builder: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    builder.add_node("retrieve", _as_graph_node(make_retrieve_node(graph, llm)))
    builder.add_node("grade", _as_graph_node(make_grade_node(llm)))
    builder.add_node("rewrite", _as_graph_node(make_rewrite_node(llm)))
    builder.add_node("answer", _as_graph_node(make_answer_node(llm, bus)))
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade", route_after_grade, {"answer": "answer", "rewrite": "rewrite"}
    )
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("answer", END)
    return builder.compile()


async def run(chat_id: str, question: str, graph: GraphService, bus: EventBus) -> None:
    """Run the agent for one question and publish its outcome on the event bus.

    Meant to be started as a background task, so it never raises. On success it
    publishes `chat.done`. On any exception it logs the full traceback with
    `logger.exception`, then publishes `chat.error` with the generic
    `AGENT_ERROR_MESSAGE`. The exception text never reaches the client.

    Args:
        chat_id: The chat the question belongs to. Put in every published payload.
        question: The user's question. It starts both `question` and `query`.
        graph: The shared graph service the retrieve node searches with.
        bus: The shared event bus for this process.
    """
    try:
        with start_chat_log(chat_id):
            llm = build_agent_llm()
            compiled = build_agent_graph(graph, llm, bus)
            initial_state: AgentState = {
                "chat_id": chat_id,
                "question": question,
                "query": question,
                "rewrites": 0,
                "retrieved": None,
                "grounded": False,
            }
            await compiled.ainvoke(initial_state, config={"callbacks": get_callback_handlers()})
    except Exception:
        logger.exception("agent run failed for chat %s", chat_id)
        bus.publish("chat.error", {"chat_id": chat_id, "message": AGENT_ERROR_MESSAGE})
        return
    bus.publish("chat.done", {"chat_id": chat_id})
