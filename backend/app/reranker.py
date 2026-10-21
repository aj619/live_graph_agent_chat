"""External HTTP reranker, and the no-op fallback, for RERANKER_* settings (app/config.py).

Two `CrossEncoderClient` implementations (graphiti_core's interface: `async def
rank(query, passages) -> list[tuple[str, float]]`, sorted most relevant first):

- `ExternalRerankerClient`: calls a dedicated rerank API over HTTP. Targets the
  request/response shape Cohere's Rerank API uses — POST {base_url}/rerank with
  {"model", "query", "documents"}, response {"results": [{"index",
  "relevance_score"}, ...]} — which Jina AI and Together AI's rerank endpoints
  also speak, being intentionally Cohere-compatible. A provider with a
  different response shape (e.g. a raw Hugging Face Text-Embeddings-Inference
  /rerank server, which replies with {"index", "score"} instead) needs its own
  client.
- `NoopRerankerClient`: returns passages unranked. Used when RERANKER_ENABLED
  is false (app/models.py) so Graphiti is never given `cross_encoder=None` —
  which would make it silently construct its own default
  `OpenAIRerankerClient()` (graphiti_core/graphiti.py), reaching for an OpenAI
  key this project never asked for. app/graph.py's no-rerank search recipe
  never calls `.rank()` in the first place, so this body does not normally
  run; it exists only to make the disabled state inert rather than undefined.
"""

from graphiti_core.cross_encoder.client import CrossEncoderClient
from httpx import AsyncBaseTransport, AsyncClient


class ExternalRerankerClient(CrossEncoderClient):
    """Reranks passages with one POST to a Cohere-compatible /rerank endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        transport: AsyncBaseTransport | None = None,
    ) -> None:
        """Build the client. `transport`, if given, replaces the real network transport
        (tests pass an `httpx.MockTransport`); base_url and the auth header are always
        applied for real, the same way for a real transport or a test one.
        """
        self._model = model
        self._client = AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
            transport=transport,
        )

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []
        response = await self._client.post(
            "/rerank",
            json={"model": self._model, "query": query, "documents": passages},
        )
        response.raise_for_status()
        results = response.json()["results"]
        ranked = [(passages[item["index"]], float(item["relevance_score"])) for item in results]
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked


class NoopRerankerClient(CrossEncoderClient):
    """Returns passages in their original order, all scored 1.0. Calls no model, no API."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 1.0) for passage in passages]
