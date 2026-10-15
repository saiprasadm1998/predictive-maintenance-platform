"""Per-key request rate limit (ARC-001 §7.1.1 429 + Retry-After, §9.3 FR 7).

A token bucket per API key, held in this web process. With several web processes each
keeps its own bucket (acceptable for the proof of concept; revisit in sub-phase 9.1).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(self, rate_per_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = rate_per_s
        self.capacity = max(rate_per_s, 1.0)
        self._clock = clock
        self._buckets: dict[int, tuple[float, float]] = {}  # key id -> (tokens, last time)
        self._lock = threading.Lock()

    def acquire(self, key_id: int) -> float:
        """Take one token. Returns 0 if allowed, else the seconds to wait before retrying."""
        with self._lock:
            now = self._clock()
            tokens, last = self._buckets.get(key_id, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key_id] = (tokens - 1, now)
                return 0.0
            self._buckets[key_id] = (tokens, now)
            return (1 - tokens) / self.rate


def retry_after_header(wait_s: float) -> str:
    return str(max(1, math.ceil(wait_s)))
