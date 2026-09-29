from __future__ import annotations
import time


class RateLimiter:
    def __init__(self, delay: float = 1.0):
        self.delay = max(0.0, delay)
        self._last = 0.0

    def wait(self):
        if self.delay <= 0:
            return
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()
