"""Tests for the in-process sliding-window rate limiter in app.ratelimit (plan §9.3).

Every test drives time through FakeClock, so nothing sleeps and nothing reads the
wall clock. The limiter only touches app.ratelimit, which has no dependency on
app.config, so no env file is loaded here.

backend/ is on sys.path through tests/conftest.py, so no sys.path shim is needed.
"""

import pytest

from app.ratelimit import (
    DEFAULT_MAX_REQUESTS,
    DEFAULT_WINDOW_SECONDS,
    RateLimiter,
)


class FakeClock:
    """A clock whose value the test sets explicitly. Calling it returns the value."""

    def __init__(self, start: float = 0.0) -> None:
        self.value: float = start

    def __call__(self) -> float:
        return self.value


def test_constructor_rejects_max_requests_zero() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0, clock=FakeClock())


def test_constructor_rejects_negative_max_requests() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_requests=-1, clock=FakeClock())


def test_constructor_rejects_zero_window() -> None:
    with pytest.raises(ValueError):
        RateLimiter(window_seconds=0, clock=FakeClock())


def test_constructor_rejects_negative_window() -> None:
    with pytest.raises(ValueError):
        RateLimiter(window_seconds=-5.0, clock=FakeClock())


def test_allow_permits_max_requests_then_refuses_within_window() -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_requests=3, window_seconds=60.0, clock=clock)

    assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is False


def test_refused_call_is_not_recorded_and_does_not_extend_window() -> None:
    # Calls at t=0, 10, 20 fill the limit of 3. The refused call at t=20 must not
    # be recorded. If it were, the window at t=60 would still hold three calls
    # after the t=0 call expires, and the check at t=60 would be refused.
    clock = FakeClock()
    limiter = RateLimiter(max_requests=3, window_seconds=60.0, clock=clock)

    clock.value = 0.0
    assert limiter.allow("token-1") is True
    clock.value = 10.0
    assert limiter.allow("token-1") is True
    clock.value = 20.0
    assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is False

    clock.value = 59.999
    assert limiter.allow("token-1") is False

    clock.value = 60.0
    assert limiter.allow("token-1") is True


def test_call_still_counts_just_before_window_length() -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)

    assert limiter.allow("token-1") is True
    clock.value = 59.999
    assert limiter.allow("token-1") is False


def test_call_is_evicted_at_exactly_window_length() -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)

    assert limiter.allow("token-1") is True
    clock.value = 60.0
    assert limiter.allow("token-1") is True


def test_window_slides_and_evicts_one_call_at_a_time_in_time_order() -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=60.0, clock=clock)

    clock.value = 0.0
    assert limiter.allow("token-1") is True
    clock.value = 30.0
    assert limiter.allow("token-1") is True
    clock.value = 31.0
    assert limiter.allow("token-1") is False

    # t=0 is 61 seconds old and is evicted. t=30 is only 31 seconds old and stays,
    # so exactly one slot is free.
    clock.value = 61.0
    assert limiter.allow("token-1") is True
    # Now t=30 and t=61 are both held. t=30 is still inside its window (31 s old),
    # so the limit is reached again.
    assert limiter.allow("token-1") is False

    # At t=90 the t=30 call is exactly 60 s old and is evicted. Only t=61 remains,
    # so one slot is free again.
    clock.value = 90.0
    assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is False


def test_keys_are_independent() -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)

    assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is False
    assert limiter.allow("key-b") is True


def test_default_constructor_allows_default_max_then_refuses() -> None:
    assert DEFAULT_MAX_REQUESTS == 10
    assert DEFAULT_WINDOW_SECONDS == 60.0

    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(DEFAULT_MAX_REQUESTS):
        assert limiter.allow("token-1") is True
    assert limiter.allow("token-1") is False


def test_expired_keys_are_swept_while_new_key_still_works() -> None:
    # Memory sanity check. Keys whose calls have all expired are removed by the
    # sweep, and a new key is still limited correctly after the sweep runs.
    clock = FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=10.0, clock=clock)

    for key in ("key-a", "key-b", "key-c"):
        assert limiter.allow(key) is True

    clock.value = 100.0
    assert limiter.allow("key-d") is True
    assert limiter.allow("key-d") is True
    assert limiter.allow("key-d") is False

    assert set(limiter._calls) == {"key-d"}
    assert limiter.allow("key-a") is True
