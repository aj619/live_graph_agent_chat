"""Per-chat timing log: which model/graph calls a chat request made, and how long each took.

Not the structured app logger (app/logging_setup.py) and not meant to be. This
writes exactly one file per chat request, under LOG_DIR, named `<chat_id>.log`,
with one row per timed call in the order it finished:

    2026-10-18T09:14:02.270Z request_received - 0.01s
    2026-10-18T09:14:03.120Z agent_llm_expand_query - 0.84s
    2026-10-18T09:14:04.510Z graph_lookup - 1.39s
    2026-10-18T09:14:04.510Z embedding - 0.21s
    2026-10-18T09:14:04.510Z reranker - 0.96s
    2026-10-18T09:14:05.900Z agent_llm_grade - 0.71s
    2026-10-18T09:14:07.300Z agent_llm_answer - 1.40s

Nothing else is written to this file: no request bodies, no facts, no prompts.

`start_chat_log(chat_id)` sets a contextvar for the duration of the chat run.
`log_call` reads it to find the right file. The contextvar is inherited by
every `asyncio` task spawned from inside that run (asyncio.gather, and any
further tasks Graphiti spawns internally during retrieve), so a single
concurrent retrieve-with-expansions call still logs every sub-call under the
same file. Outside a chat run (nothing has called `start_chat_log`), `log_call`
is a no-op — insertion and the graph snapshot endpoint do not write here.
"""

import time
from collections.abc import Awaitable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")

_active_chat_id: ContextVar[str | None] = ContextVar("_active_chat_id", default=None)


@contextmanager
def start_chat_log(chat_id: str) -> Any:
    """Route every `log_call` made inside this block to logs/<chat_id>.log."""
    token = _active_chat_id.set(chat_id)
    try:
        yield
    finally:
        _active_chat_id.reset(token)


def log_call(event: str, seconds: float) -> None:
    """Append one timing row for `event` to the active chat's log file, if any."""
    chat_id = _active_chat_id.get()
    if chat_id is None:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    line = f"{timestamp} {event} - {seconds:.2f}s\n"
    with (LOG_DIR / f"{chat_id}.log").open("a", encoding="utf-8") as handle:
        handle.write(line)


async def timed[T](event: str, call: Awaitable[T]) -> T:
    """Await `call`, log its wall time under `event`, and return its result."""
    start = time.monotonic()
    try:
        return await call
    finally:
        log_call(event, time.monotonic() - start)


def wrap_timed_method(obj: object, method_name: str, event: str) -> None:
    """Replace `obj.<method_name>` with a version that logs its wall time under `event`.

    The original bound method is looked up once and kept, so `obj.<method_name>`
    is unaffected for any other instance. Used only on model clients this
    process constructs itself (app/models.py); test-injected fakes are never
    wrapped, so existing tests that assert call counts or arguments on a fake
    see it unchanged.
    """
    original = getattr(obj, method_name)

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        return await timed(event, original(*args, **kwargs))

    setattr(obj, method_name, wrapped)
