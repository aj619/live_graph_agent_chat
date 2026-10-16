"""In-process fan-out event bus for Server-Sent Events (plan §4 "events", §6.2).

The app runs as a single FastAPI worker process (plan decision D6), so the bus
lives in memory and needs no external broker.

- Each subscriber owns a bounded ``asyncio.Queue``. A slow consumer cannot grow
  memory without limit and cannot slow down other consumers.
- ``EventBus.publish`` never waits and never raises because of a subscriber. If a
  subscriber's queue is full, the subscriber is stalled: the bus drops it, clears
  its queue, and wakes its stream so the stream ends. The drop is logged.
- ``stream_events`` is the async generator a route turns into a
  ``text/event-stream`` body. It yields a connected comment first, then one SSE
  block per published event, and a keep-alive comment after each interval with
  no event.

The bus is generic. It carries whatever ``event_type`` and JSON-serializable
``data`` the caller passes, and it does not know the event names in plan §6.2.

Keep-alive interval and queue size are module constants, not ``Settings``
entries, because the plan does not make them configurable.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_SECONDS: float = 15.0
"""Seconds with no event before a keep-alive comment is sent (plan §6.2)."""

SUBSCRIBER_QUEUE_MAXSIZE: int = 256
"""Maximum queued SSE blocks per subscriber. A full queue marks the subscriber as stalled."""

CONNECTED_COMMENT: str = ": connected\n\n"
KEEPALIVE_COMMENT: str = ": keep-alive\n\n"

# Internal wake-up marker. It is never a valid SSE block, so it cannot be confused with one.
_CLOSE: None = None


def format_sse(event_type: str, data: Any) -> str:
    """Return one SSE block: an ``event:`` line, a ``data:`` line, and a blank line.

    ``data`` is serialized with ``json.dumps``. Its output contains no raw line
    breaks, so it always fits on one ``data:`` line.

    Raises:
        ValueError: if ``event_type`` is empty or contains a line break. Such a
            name would break the SSE framing. This is a caller bug, not a
            subscriber problem.
        TypeError: if ``data`` is not JSON-serializable.
    """
    if not event_type or "\n" in event_type or "\r" in event_type:
        raise ValueError("event_type must be non-empty and contain no line breaks")
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n"


class EventBus:
    """Fan out published events to every current subscriber."""

    def __init__(self, queue_maxsize: int = SUBSCRIBER_QUEUE_MAXSIZE) -> None:
        if queue_maxsize < 1:
            raise ValueError("queue_maxsize must be at least 1")
        self._queue_maxsize = queue_maxsize
        self._subscribers: set[asyncio.Queue[str | None]] = set()

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers. Dropped and unsubscribed queues are not counted."""
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[str | None]:
        """Register a new subscriber and return its queue. Pass it to ``unsubscribe`` when done."""
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        """Stop delivering to ``queue``. Calling it again, or for a dropped queue, does nothing."""
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: Any) -> None:
        """Send one event to every current subscriber.

        Never blocks. It raises only for bad arguments, never for a subscriber.

        The event is serialized once and the same SSE block is queued for each
        subscriber. A subscriber whose queue is full is dropped. Other subscribers
        still receive the event.
        """
        block = format_sse(event_type, data)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(block)
            except asyncio.QueueFull:
                self._drop(queue)

    def _drop(self, queue: asyncio.Queue[str | None]) -> None:
        """Remove a stalled subscriber, discard its backlog, and wake its stream so it ends."""
        self._subscribers.discard(queue)
        while not queue.empty():
            queue.get_nowait()
        # The queue was just emptied, so this put cannot fail (maxsize >= 1).
        queue.put_nowait(_CLOSE)
        logger.warning(
            "Dropped stalled event subscriber: queue full at %d items",
            self._queue_maxsize,
        )


async def stream_events(
    bus: EventBus,
    keepalive_interval: float = KEEPALIVE_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE text for one client until the bus drops it or the consumer stops iterating.

    Yields the connected comment first. Then it yields each event block as it
    arrives. When ``keepalive_interval`` seconds pass with no event, it yields the
    keep-alive comment. The interval restarts after every event. The subscription
    is removed when the generator is closed, cancelled, or ends.
    """
    queue = bus.subscribe()
    try:
        yield CONNECTED_COMMENT
        while True:
            try:
                block = await asyncio.wait_for(queue.get(), timeout=keepalive_interval)
            except TimeoutError:
                yield KEEPALIVE_COMMENT
                continue
            if block is _CLOSE:
                return
            yield block
    finally:
        bus.unsubscribe(queue)
