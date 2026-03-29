"""Sliding-window asyncio rate limiter for Kalshi REST calls.

In-process implementation — no external dependencies needed for a
single-process, single-user backend.  A Redis-backed limiter would only be
necessary for multi-process coordination; this app is a single FastAPI
process.

Design
------
Uses a deque to track the monotonic timestamp of every call that entered the
window in the last `period_s` seconds (default 1.0 s).  An asyncio.Lock
serializes all callers through the gate so that:

  • Only one caller advances at a time (no two calls race through simultaneously).
  • The deque is mutated safely without async-safe collections.
  • The effective throughput is strictly ≤ max_calls per period_s.

When the window is full the caller sleeps until the oldest call's timestamp
plus period_s, then re-checks.  This produces precise millisecond-level
throttling without busy-waiting.

Usage
-----
    limiter = RateLimiter(max_calls=10)   # 10 calls/sec
    await limiter.acquire()               # blocks until a slot is available
    response = await http_client.get(...)
"""

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window async rate limiter.

    Guarantees ≤ max_calls starts within any rolling period_s-second window.
    All callers are serialized through an asyncio.Lock — only one proceeds
    through acquire() at a time, preventing thundering-herd bursts.
    """

    def __init__(self, max_calls: int = 10, period_s: float = 1.0) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        if period_s <= 0:
            raise ValueError("period_s must be > 0")
        self._max_calls = max_calls
        self._period_s = period_s
        self._lock = asyncio.Lock()
        self._window: deque[float] = deque()

    @property
    def max_calls(self) -> int:
        return self._max_calls

    @property
    def period_s(self) -> float:
        return self._period_s

    async def acquire(self) -> None:
        """Block until a call slot is available, then claim it.

        After returning the caller may immediately fire their HTTP request.
        The slot is considered consumed at the moment acquire() returns.
        """
        async with self._lock:
            while True:
                now = time.monotonic()

                # Evict calls that have left the rolling window.
                while self._window and now - self._window[0] >= self._period_s:
                    self._window.popleft()

                if len(self._window) < self._max_calls:
                    # Slot available — record this call and return.
                    self._window.append(now)
                    return

                # Window is full — compute exact sleep needed for oldest slot to expire.
                oldest = self._window[0]
                sleep_for = self._period_s - (now - oldest)
                if sleep_for > 0:
                    logger.debug(
                        "Rate limiter: %d/%d slots used in %.3fs window — waiting %.3fs.",
                        len(self._window),
                        self._max_calls,
                        self._period_s,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                # Re-enter the loop to evict the now-expired slot and claim it.
