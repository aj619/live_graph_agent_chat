"""Shared fakes for the backend tests (plan §6, §8).

Two structural fakes with no dependency on `app.config`, the real Graphiti
client, or LangChain. Neither needs a `.env` file, a running Neo4j, or an LLM
endpoint.

- `FakeGraphService` mirrors the four async methods of `app.graph.GraphService`
  that the insert, recovery, deletion, and agent tests use. It keeps episodes in
  memory and records every call. It can be told to raise on the Nth call of any
  of those methods.
- `FakeChatModel` mirrors the async `ainvoke` and `astream` calls that
  `app.agent` makes on the agent chat model. It returns a fixed reply and fixed
  stream tokens, and it records every prompt it receives.

Both fakes are plain classes, so tests import them directly:

    from tests.fakes import FakeChatModel, FakeGraphService
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Annotations only. The runtime import of app.graph is deferred to the
    # default-value helpers below, so importing this module never loads app.config.
    from app.graph import GraphSnapshot, RetrieveResult

__all__ = ["FakeChatModel", "FakeGraphService", "FakeMessage"]


def _empty_retrieve_result() -> RetrieveResult:
    """Build the default `RetrieveResult`. The app.graph import happens only when called."""
    from app.graph import RetrieveResult

    return RetrieveResult()


def _empty_snapshot() -> GraphSnapshot:
    """Build the default `GraphSnapshot`. The app.graph import happens only when called."""
    from app.graph import GraphSnapshot

    return GraphSnapshot()


class FakeFailure(RuntimeError):
    """Raised by a fake when a test has told it to fail on that call."""


@dataclass(frozen=True)
class FakeMessage:
    """A message-like object with the one attribute the agent reads: `content`."""

    content: str


class FakeGraphService:
    """In-memory stand-in for `app.graph.GraphService`.

    Constructor arguments:
        fail_on: maps a method name (`"insert_episode"`, `"remove_episode"`,
            `"retrieve"`, or `"snapshot"`) to the 1-indexed call number that
            raises `FakeFailure`. All other calls succeed.
        fail_insert_on_call: shorthand for `fail_on={"insert_episode": n}`.
            Merged into `fail_on` when both are given.
        retrieve_result: what `retrieve()` returns for any query not in
            `retrieve_results_by_query`. Defaults to an empty `RetrieveResult`.
        retrieve_results_by_query: per-query overrides for `retrieve()`, e.g. to
            give an expanded-query variant a different result than the original
            query. A query not listed here falls back to `retrieve_result`.
        snapshot_result: what `snapshot()` returns. Defaults to an empty
            `GraphSnapshot`.

    State a test can inspect:
        episodes: `episode_uuid -> {"name", "body", "source_description"}` for
            every episode that was inserted and not yet removed.
        insert_calls: one dict per `insert_episode` attempt, in order, with
            keys `episode_uuid`, `name`, `body`, `source_description`. Failed
            attempts are recorded too, but they do not add to `episodes`.
        remove_calls: one UUID per `remove_episode` call, in order, including
            UUIDs that were not present.
        retrieve_queries: the query string of each `retrieve()` call, in order.
        snapshot_calls: how many times `snapshot()` was called.
        call_counts: total calls per method name, including failed calls.

    `remove_episode` on an unknown UUID does not raise, which matches the real
    `GraphService.remove_episode`.
    """

    def __init__(
        self,
        *,
        fail_on: dict[str, int] | None = None,
        fail_insert_on_call: int | None = None,
        retrieve_result: RetrieveResult | None = None,
        retrieve_results_by_query: dict[str, RetrieveResult] | None = None,
        snapshot_result: GraphSnapshot | None = None,
    ) -> None:
        self._fail_on: dict[str, int] = dict(fail_on or {})
        if fail_insert_on_call is not None:
            self._fail_on["insert_episode"] = fail_insert_on_call
        # None means "return an empty result"; the app.graph import is deferred until then.
        self._retrieve_result: RetrieveResult | None = retrieve_result
        self._retrieve_results_by_query: dict[str, RetrieveResult] = dict(
            retrieve_results_by_query or {}
        )
        self._snapshot_result: GraphSnapshot | None = snapshot_result

        self.episodes: dict[str, dict[str, str]] = {}
        self.insert_calls: list[dict[str, str]] = []
        self.remove_calls: list[str] = []
        self.retrieve_queries: list[str] = []
        self.snapshot_calls: int = 0
        self.call_counts: dict[str, int] = {}

    def _tick(self, method: str) -> None:
        """Count one call to `method` and raise if the test asked for failure on it."""
        count = self.call_counts.get(method, 0) + 1
        self.call_counts[method] = count
        if self._fail_on.get(method) == count:
            raise FakeFailure(f"fake {method} failed on call {count}")

    async def insert_episode(
        self,
        episode_uuid: str,
        name: str,
        body: str,
        source_description: str,
    ) -> None:
        """Record the attempt, then store the episode unless this call is set to fail."""
        self.insert_calls.append(
            {
                "episode_uuid": episode_uuid,
                "name": name,
                "body": body,
                "source_description": source_description,
            }
        )
        self._tick("insert_episode")
        self.episodes[episode_uuid] = {
            "name": name,
            "body": body,
            "source_description": source_description,
        }

    async def remove_episode(self, episode_uuid: str) -> None:
        """Delete the episode if present. A missing UUID is skipped without an error."""
        self.remove_calls.append(episode_uuid)
        self._tick("remove_episode")
        self.episodes.pop(episode_uuid, None)

    async def retrieve(self, query: str) -> RetrieveResult:
        """Return the configured result for `query` and record the query."""
        self.retrieve_queries.append(query)
        self._tick("retrieve")
        if query in self._retrieve_results_by_query:
            return self._retrieve_results_by_query[query]
        if self._retrieve_result is None:
            return _empty_retrieve_result()
        return self._retrieve_result

    async def snapshot(self) -> GraphSnapshot:
        """Return the configured snapshot and count the call."""
        self.snapshot_calls += 1
        self._tick("snapshot")
        if self._snapshot_result is None:
            return _empty_snapshot()
        return self._snapshot_result


class FakeChatModel:
    """Fixed-reply stand-in for the agent chat model.

    Constructor arguments:
        invoke_reply: the `content` of the message `ainvoke` returns on every
            call. Use `"YES"` or `"NO"` for the grader.
        stream_tokens: the `content` of each chunk `astream` yields, in order.
            Defaults to `["answer"]`.

    State a test can inspect:
        invoke_calls: the prompt of each `ainvoke` call, in order.
        stream_calls: the prompt of each `astream` call, in order.

    The `config` argument is accepted and ignored, so the fake fits the
    `config=...` calls in `app.agent`.
    """

    def __init__(
        self,
        *,
        invoke_reply: str = "YES",
        stream_tokens: list[str] | None = None,
    ) -> None:
        self._invoke_reply = invoke_reply
        self._stream_tokens: list[str] = (
            list(stream_tokens) if stream_tokens is not None else ["answer"]
        )
        self.invoke_calls: list[str] = []
        self.stream_calls: list[str] = []

    async def ainvoke(self, prompt: str, config: dict[str, Any] | None = None) -> FakeMessage:
        """Record the prompt and return a message whose content is `invoke_reply`."""
        self.invoke_calls.append(prompt)
        return FakeMessage(content=self._invoke_reply)

    async def astream(
        self, prompt: str, config: dict[str, Any] | None = None
    ) -> AsyncIterator[FakeMessage]:
        """Record the prompt, then yield one chunk per entry in `stream_tokens`."""
        self.stream_calls.append(prompt)
        for token in self._stream_tokens:
            yield FakeMessage(content=token)
