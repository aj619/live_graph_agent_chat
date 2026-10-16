"""Unit tests for the in-process SSE event bus (plan §4 "events", §6.2).

No I/O: the bus and the stream are pure asyncio over in-memory queues. No
settings, .env file, or network is needed. Every await that could hang is
wrapped in asyncio.wait_for with a short timeout, so a broken test fails fast.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import cast

import pytest

from app import events as events_module
from app.events import (
    CONNECTED_COMMENT,
    KEEPALIVE_COMMENT,
    EventBus,
    format_sse,
    stream_events,
)

WAIT_TIMEOUT = 1.0
SHORT_KEEPALIVE = 0.05


async def _next(gen: AsyncGenerator[str]) -> str:
    return await asyncio.wait_for(anext(gen), timeout=WAIT_TIMEOUT)


async def _get(queue: asyncio.Queue[str | None]) -> str | None:
    return await asyncio.wait_for(queue.get(), timeout=WAIT_TIMEOUT)


def _open_stream(bus: EventBus, keepalive_interval: float = 15.0) -> AsyncGenerator[str]:
    """Return stream_events as an async generator so the test can call aclose()."""
    return cast(AsyncGenerator[str], stream_events(bus, keepalive_interval))


def _drain(queue: asyncio.Queue[str | None]) -> list[str | None]:
    items: list[str | None] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


# --- format_sse -------------------------------------------------------------


def test_format_sse_produces_exact_block_with_escaped_data() -> None:
    block = format_sse("foo", {"msg": 'a "quote"\nline'})

    assert block == 'event: foo\ndata: {"msg":"a \\"quote\\"\\nline"}\n\n'
    # Three line breaks: the event line, the data line, and the blank separator.
    # The raw newline in the payload must not add a line.
    assert block.count("\n") == 3
    data_lines = [line for line in block.split("\n") if line.startswith("data: ")]
    assert len(data_lines) == 1


def test_format_sse_rejects_empty_event_type() -> None:
    with pytest.raises(ValueError):
        format_sse("", {"a": 1})


@pytest.mark.parametrize("event_type", ["foo\nbar", "foo\rbar", "foo\n"])
def test_format_sse_rejects_event_type_with_line_break(event_type: str) -> None:
    with pytest.raises(ValueError):
        format_sse(event_type, {"a": 1})


def test_format_sse_rejects_non_json_serializable_data() -> None:
    with pytest.raises(TypeError):
        format_sse("foo", {1, 2, 3})


def test_format_sse_rejects_arbitrary_object_data() -> None:
    with pytest.raises(TypeError):
        format_sse("foo", object())


# --- EventBus construction --------------------------------------------------


@pytest.mark.parametrize("queue_maxsize", [0, -1])
def test_event_bus_rejects_queue_maxsize_below_one(queue_maxsize: int) -> None:
    with pytest.raises(ValueError):
        EventBus(queue_maxsize=queue_maxsize)


# --- delivery and subscriber bookkeeping -----------------------------------


async def test_publish_delivers_exact_block_to_subscriber() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    assert bus.subscriber_count == 1

    bus.publish("graph.updated", {"node": "n1"})

    assert await _get(queue) == format_sse("graph.updated", {"node": "n1"})

    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0


async def test_publish_fans_out_identical_block_to_every_subscriber() -> None:
    bus = EventBus()
    first = bus.subscribe()
    second = bus.subscribe()
    assert bus.subscriber_count == 2

    bus.publish("status", {"ok": True})

    expected = format_sse("status", {"ok": True})
    assert await _get(first) == expected
    assert await _get(second) == expected


async def test_publish_with_no_subscribers_does_nothing() -> None:
    bus = EventBus()

    bus.publish("status", {"ok": True})

    assert bus.subscriber_count == 0


async def test_unsubscribe_is_idempotent_and_count_never_goes_negative() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    other = bus.subscribe()

    bus.unsubscribe(queue)
    bus.unsubscribe(queue)
    assert bus.subscriber_count == 1

    stranger: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)
    bus.unsubscribe(stranger)
    assert bus.subscriber_count == 1

    bus.unsubscribe(other)
    assert bus.subscriber_count == 0


async def test_unsubscribed_queue_receives_no_further_events() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)

    bus.publish("status", {"ok": True})

    assert _drain(queue) == []


# --- stalled-subscriber drop ------------------------------------------------


async def test_stalled_subscriber_is_dropped_without_affecting_healthy_one() -> None:
    bus = EventBus(queue_maxsize=1)
    stalled = bus.subscribe()
    healthy = bus.subscribe()
    assert bus.subscriber_count == 2

    # First publish fills both queues. The stalled one is never drained.
    bus.publish("tick", {"n": 1})
    assert await _get(healthy) == format_sse("tick", {"n": 1})

    # Second publish overflows the stalled queue. publish must not raise.
    bus.publish("tick", {"n": 2})

    assert bus.subscriber_count == 1
    # The stalled queue was drained and holds only the close sentinel.
    assert _drain(stalled) == [None]
    # The healthy subscriber still got every event, in order.
    assert await _get(healthy) == format_sse("tick", {"n": 2})

    # Later publishes keep reaching the healthy subscriber.
    bus.publish("tick", {"n": 3})
    assert await _get(healthy) == format_sse("tick", {"n": 3})


async def test_publish_does_not_raise_when_a_subscriber_queue_is_full() -> None:
    bus = EventBus(queue_maxsize=2)
    bus.subscribe()  # never drained

    for n in range(5):
        bus.publish("tick", {"n": n})

    assert bus.subscriber_count == 0


async def test_dropped_subscriber_is_logged_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus(queue_maxsize=1)
    bus.subscribe()

    with caplog.at_level(logging.WARNING, logger=events_module.__name__):
        bus.publish("tick", {"n": 1})
        bus.publish("tick", {"n": 2})

    warnings = [
        record
        for record in caplog.records
        if record.name == events_module.__name__ and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


# --- stream_events ----------------------------------------------------------


async def test_stream_events_yields_connected_then_published_block() -> None:
    bus = EventBus()
    gen = _open_stream(bus)
    try:
        assert await _next(gen) == CONNECTED_COMMENT
        assert bus.subscriber_count == 1

        bus.publish("graph.updated", {"node": "n1"})

        assert await _next(gen) == format_sse("graph.updated", {"node": "n1"})
    finally:
        await gen.aclose()


async def test_stream_events_yields_keepalive_after_quiet_interval_and_keeps_going() -> None:
    bus = EventBus()
    gen = _open_stream(bus, SHORT_KEEPALIVE)
    try:
        assert await _next(gen) == CONNECTED_COMMENT
        assert await _next(gen) == KEEPALIVE_COMMENT
        assert await _next(gen) == KEEPALIVE_COMMENT
    finally:
        await gen.aclose()


async def test_stream_events_ends_when_bus_drops_its_subscriber() -> None:
    bus = EventBus(queue_maxsize=1)
    gen = _open_stream(bus)
    try:
        assert await _next(gen) == CONNECTED_COMMENT

        # The stream is not being read, so its queue fills and the bus drops it.
        bus.publish("tick", {"n": 1})
        bus.publish("tick", {"n": 2})

        assert bus.subscriber_count == 0
        with pytest.raises(StopAsyncIteration):
            await _next(gen)
    finally:
        await gen.aclose()


async def test_stream_events_unsubscribes_when_closed() -> None:
    bus = EventBus()
    gen = _open_stream(bus)
    assert await _next(gen) == CONNECTED_COMMENT
    assert bus.subscriber_count == 1

    await gen.aclose()

    assert bus.subscriber_count == 0


async def test_stream_events_unsubscribes_when_consumer_task_is_cancelled() -> None:
    bus = EventBus()

    async def consume() -> None:
        async for _ in stream_events(bus, keepalive_interval=SHORT_KEEPALIVE):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(SHORT_KEEPALIVE * 2)
    assert bus.subscriber_count == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)

    assert bus.subscriber_count == 0
