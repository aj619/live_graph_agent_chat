"""In-process sliding-window rate limiter (plan §9.3 "Application security").

Plan §9.3 asks for a rate limit on ``POST /api/chat`` per API token. The plan
accepts a simple in-memory limiter, and the app runs as a single FastAPI worker
process (plan decision D6), so the counters live in memory. This limiter is
single-process only. Running several workers would give each worker its own
counts, so a caller could exceed the limit by spreading requests across them.

- ``RateLimiter.allow(key)`` returns ``True`` and records the call when fewer
  than ``max_requests`` calls with the same key fall inside the last
  ``window_seconds``. It returns ``False`` and does not record the call when the
  limit is reached. A refused call does not extend the window.
- The window slides. A call stops counting once it is ``window_seconds`` old.
- Keys are independent. One key's usage never affects another key's count.
- The limiter is generic. The key is any ``str``. This module does not know what
  a key means, and it does not know about API tokens. Chat is the only route that
  uses it (plan §9.3), but that is wiring in a later task, not a limit of this module.
- The check is synchronous and does no I/O, so it is safe on a request path.

Memory: each key keeps only the timestamps inside its window. A key whose
timestamps have all expired is removed when it is next checked. Keys that are
never checked again are removed by a sweep that runs at most once per window.
So the table holds only keys seen within about one window of the newest check.

The clock is injectable (``time.monotonic`` by default), so tests can control
time without sleeping.

The limit and window are module constants, not ``Settings`` entries, because
the plan's configuration contract (plan §5) does not define a rate-limit
variable. The same applies to the constants in ``events.py``.
"""

import time
from collections import deque
from collections.abc import Callable

DEFAULT_MAX_REQUESTS: int = 10
"""Calls allowed per key within one window. Ten chat calls per minute per token is
generous for one person using the chat, and it limits a runaway client."""

DEFAULT_WINDOW_SECONDS: float = 60.0
"""Length of the sliding window, in seconds (see ``DEFAULT_MAX_REQUESTS``)."""


class RateLimiter:
    """Allow at most ``max_requests`` calls per key in any ``window_seconds`` span.

    Raises:
        ValueError: if ``max_requests`` is less than 1, or ``window_seconds`` is not
            greater than 0. These are caller bugs, detected at construction.
    """

    def __init__(
        self,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if not window_seconds > 0:
            raise ValueError("window_seconds must be greater than 0")
        self._max_requests: int = max_requests
        self._window_seconds: float = window_seconds
        self._clock: Callable[[], float] = clock
        self._calls: dict[str, deque[float]] = {}
        self._next_sweep: float = clock() + window_seconds

    def allow(self, key: str) -> bool:
        """Return ``True`` and count the call if ``key`` is under its limit.

        Return ``False`` without counting the call if ``key`` has already used
        ``max_requests`` calls within the current window.
        """
        now = self._clock()
        if now >= self._next_sweep:
            self._sweep(now)
        calls = self._calls.get(key)
        if calls is None:
            calls = deque()
            self._calls[key] = calls
        self._evict_expired(calls, now)
        if len(calls) >= self._max_requests:
            return False
        calls.append(now)
        return True

    def _evict_expired(self, calls: deque[float], now: float) -> None:
        """Drop timestamps that are at least one window old. Calls are in time order."""
        while calls and now - calls[0] >= self._window_seconds:
            calls.popleft()

    def _sweep(self, now: float) -> None:
        """Remove every key with no calls left inside its window."""
        for key in list(self._calls):
            calls = self._calls[key]
            self._evict_expired(calls, now)
            if not calls:
                del self._calls[key]
        self._next_sweep = now + self._window_seconds
