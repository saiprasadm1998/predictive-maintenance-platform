"""API helpers that need no database: rate limiting and key format."""

from __future__ import annotations

from pmp.api.ratelimit import RateLimiter, retry_after_header
from pmp.core.apikeys import generate_key, parse_prefix


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_allows_the_rate_then_refuses_with_a_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock)
    assert limiter.acquire(1) == 0
    assert limiter.acquire(1) == 0
    wait = limiter.acquire(1)
    assert 0 < wait <= 0.5
    assert retry_after_header(wait) == "1"
    clock.now += 0.5
    assert limiter.acquire(1) == 0  # one token refilled


def test_rate_limit_is_per_key() -> None:
    limiter = RateLimiter(1.0, FakeClock())
    assert limiter.acquire(1) == 0
    assert limiter.acquire(1) > 0
    assert limiter.acquire(2) == 0


def test_generated_keys_have_a_lookup_prefix() -> None:
    key, prefix = generate_key()
    assert key.startswith(f"pmp_{prefix}_")
    assert len(prefix) == 12
    assert parse_prefix(key) == prefix
    assert len(key) > 50


def test_malformed_keys_have_no_prefix() -> None:
    for bad in ("", "pmp_", "abc_123456789012_x", "pmp_short_x", "Bearer x"):
        assert parse_prefix(bad) is None
