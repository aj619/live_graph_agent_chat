"""Tests for app.reranker: ExternalRerankerClient and NoopRerankerClient.

ExternalRerankerClient makes no real network call: its `transport` constructor
argument swaps in an httpx.MockTransport in place of the real network transport,
while base_url and the auth header are still applied by the client's own __init__
exactly as they are for a real transport, so those are genuinely under test too.
"""

import json

import httpx
import pytest

from app.reranker import ExternalRerankerClient, NoopRerankerClient


async def test_rank_sends_model_query_and_documents_and_bearer_key() -> None:
    sent: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["auth"] = request.headers["authorization"]
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    reranker = ExternalRerankerClient(
        base_url="https://rerank.invalid/v1",
        api_key="secret-key",
        model="rerank-model-1",
        transport=httpx.MockTransport(handle),
    )

    await reranker.rank("a query", ["passage one"])

    assert sent["url"] == "https://rerank.invalid/v1/rerank"
    assert sent["auth"] == "Bearer secret-key"
    assert sent["body"] == {
        "model": "rerank-model-1",
        "query": "a query",
        "documents": ["passage one"],
    }


async def test_rank_maps_index_back_to_its_passage_and_sorts_by_score_descending() -> None:
    # passages[0] ("low score passage") scores 0.2; passages[1] ("high score
    # passage") scores 0.9 — listed out of index order to prove rank() maps by
    # `index`, not by the order `results` arrived in.
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )

    reranker = ExternalRerankerClient(
        base_url="https://rerank.invalid/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handle),
    )

    ranked = await reranker.rank("q", ["low score passage", "high score passage"])

    assert ranked == [("high score passage", 0.9), ("low score passage", 0.2)]


async def test_rank_with_no_passages_returns_empty_without_a_request() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent for an empty passage list")

    reranker = ExternalRerankerClient(
        base_url="https://rerank.invalid/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handle),
    )

    assert await reranker.rank("q", []) == []


async def test_rank_raises_on_an_http_error_response() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid key"})

    reranker = ExternalRerankerClient(
        base_url="https://rerank.invalid/v1",
        api_key="wrong-key",
        model="m",
        transport=httpx.MockTransport(handle),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await reranker.rank("q", ["passage"])


async def test_noop_reranker_keeps_order_and_scores_everything_1_0() -> None:
    reranker = NoopRerankerClient()

    ranked = await reranker.rank("q", ["first", "second", "third"])

    assert ranked == [("first", 1.0), ("second", 1.0), ("third", 1.0)]


async def test_noop_reranker_with_no_passages_returns_empty() -> None:
    reranker = NoopRerankerClient()

    assert await reranker.rank("q", []) == []
