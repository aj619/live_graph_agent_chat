"""Model clients for Graphiti (plan §6.6).

Builds the three model clients Graphiti needs from `Settings`:

- LLM: OpenAIGenericClient configured with LLMConfig.
- Embedder: OpenAIEmbedder configured with OpenAIEmbedderConfig.
- Reranker: BGERerankerClient — a local sentence-transformers cross-encoder
  (BAAI/bge-reranker-v2-m3), not an API client. No Settings go into it: it has
  no base URL or key to configure, and downloads its model weights from the
  HuggingFace Hub on first use instead of calling a configured provider.

The LLM and embedder use the OpenAI-compatible base URL and key from Settings.
No model name, URL, key, or provider name is written in this file.

Constructing the LLM/embedder clients does not contact a model server. The
underlying HTTP client only stores the base URL and key; the first network
call happens when Graphiti calls the client. Constructing the reranker *can*
contact a server (the HuggingFace Hub) the first time it runs, to fetch model
weights; after that they're cached on disk and no network call is needed.

Tests inject a fake client for any of the three by passing it as a keyword
override. Only the clients that are not supplied are built from Settings.
"""

from dataclasses import dataclass
from typing import Any

from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from app.config import Settings, settings


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

    return ModelClients(
        llm_client=llm_client if llm_client is not None else OpenAIGenericClient(config=llm_config),
        embedder=embedder if embedder is not None else OpenAIEmbedder(config=embedder_config),
        # Local cross-encoder (sentence-transformers, BAAI/bge-reranker-v2-m3) — no API
        # calls, so no provider rate limit to exceed. Takes no config: it has nothing to
        # point at a base URL or key for.
        reranker=reranker if reranker is not None else BGERerankerClient(),  # type: ignore[no-untyped-call]
    )
