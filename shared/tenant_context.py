"""TenantContext — per-deployment isolation and rate limiting."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter (resets on process restart)."""

    def __init__(self, max_calls_per_hour: int = 0) -> None:
        self._max = max_calls_per_hour
        self._window: deque[float] = deque()

    def check_and_consume(self) -> bool:
        if self._max == 0:
            return True
        now = time.time()
        cutoff = now - 3600
        while self._window and self._window[0] < cutoff:
            self._window.popleft()
        if len(self._window) >= self._max:
            return False
        self._window.append(now)
        return True

    @property
    def calls_in_window(self) -> int:
        now = time.time()
        cutoff = now - 3600
        return sum(1 for t in self._window if t >= cutoff)


@dataclass
class TenantContext:
    tenant_id: str = "default"
    rate_limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )
