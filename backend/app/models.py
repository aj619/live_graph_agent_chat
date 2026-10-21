"""Model clients for Graphiti (plan §6.6).

Builds the three model clients Graphiti needs from `Settings`:

- LLM: OpenAIGenericClient configured with LLMConfig.
- Embedder: OpenAIEmbedder configured with OpenAIEmbedderConfig.
- Reranker: depends on RERANKER_ENABLED (app/config.py). When true,
  `ExternalRerankerClient` (app/reranker.py) calls the Cohere-compatible
  RERANKER_BASE_URL/API_KEY/MODEL endpoint. When false, `NoopRerankerClient`
  is used instead and no reranking call is made at all — app/graph.py also
  switches its search recipe off cross-encoder reranking in that case, so
  `.rank()` is never even called in normal operation.

The LLM and embedder use the OpenAI-compatible base URL and key from Settings.
No model name, URL, key, or provider name is written in this file.

Constructing the LLM/embedder clients does not contact a model server. The
underlying HTTP client only stores the base URL and key; the first network
call happens when Graphiti calls the client. Constructing the reranker never
contacts a server either, for the same reason.

Tests inject a fake client for any of the three by passing it as a keyword
override. Only the clients that are not supplied are built from Settings.
"""

from dataclasses import dataclass
from typing import Any

from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from app.call_logging import wrap_timed_method
from app.config import Settings, settings
from app.reranker import ExternalRerankerClient, NoopRerankerClient


@dataclass(frozen=True)
class ModelClients:
    """The three model clients that Graphiti takes as constructor arguments."""

    llm_client: Any
    embedder: Any
    reranker: Any


def build_model_clients(
    cfg: Settings = settings,
    *,
    llm_client: Any | None = None,
    embedder: Any | None = None,
    reranker: Any | None = None,
) -> ModelClients:
    """Return the LLM client, embedder, and reranker.

    Args:
        cfg: The settings to build from. Defaults to the module-level `settings`.
        llm_client: If given, used as the LLM client and no client is built for it.
        embedder: If given, used as the embedder and no embedder is built for it.
        reranker: If given, used as the reranker and no reranker is built for it.
    """
    llm_config = LLMConfig(
        api_key=cfg.LLM_API_KEY,
        base_url=cfg.LLM_BASE_URL,
        model=cfg.LLM_MODEL,
        small_model=cfg.LLM_SMALL_MODEL,
        temperature=cfg.LLM_TEMPERATURE,
    )
    embedder_config = OpenAIEmbedderConfig(
        api_key=cfg.EMBEDDING_API_KEY,
        base_url=cfg.EMBEDDING_BASE_URL,
        embedding_model=cfg.EMBEDDING_MODEL,
    )

    built_llm_client = llm_client is None
    built_embedder = embedder is None
    built_reranker = reranker is None

    resolved_llm_client = (
        llm_client if llm_client is not None else OpenAIGenericClient(config=llm_config)
    )
    resolved_embedder = (
        embedder if embedder is not None else OpenAIEmbedder(config=embedder_config)
    )
    if reranker is not None:
        resolved_reranker = reranker
    elif cfg.RERANKER_ENABLED:
        resolved_reranker = ExternalRerankerClient(
            base_url=cfg.RERANKER_BASE_URL,
            api_key=cfg.RERANKER_API_KEY,
            model=cfg.RERANKER_MODEL,
        )
    else:
        resolved_reranker = NoopRerankerClient()

    # Per-chat timing log (app/call_logging.py): only wrap clients built here, from
    # Settings, never a caller-supplied (test) client, so existing tests that assert
    # call counts or arguments on a fake see it unchanged.
    if built_llm_client:
        wrap_timed_method(resolved_llm_client, "generate_response", "graph_llm")
    if built_embedder:
        wrap_timed_method(resolved_embedder, "create", "embedding")
        wrap_timed_method(resolved_embedder, "create_batch", "embedding")
    if built_reranker:
        wrap_timed_method(resolved_reranker, "rank", "reranker")

    return ModelClients(
        llm_client=resolved_llm_client,
        embedder=resolved_embedder,
        reranker=resolved_reranker,
    )
