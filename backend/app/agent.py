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

import re
from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import Settings, settings
from app.graph import GraphService, RetrieveResult
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
