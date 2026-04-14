"""util.py — Per-IP token-bucket rate limiter.

Mirrors the Go util.go behaviour:
  - 100 requests per 60 seconds, burst of 10
  - Two-generation map rotation at MAX_ENTRIES to bound memory usage
"""

import threading
import time

MAX_ENTRIES = 10_000  # rotate when current map hits this size (~2.5 MB)


class _TokenBucket:
    """Thread-safe token bucket: refill at ``rate`` tokens/sec, cap at ``burst``."""

    __slots__ = ("rate", "burst", "tokens", "last", "_lock")

    def __init__(self, rate: float = 100 / 60, burst: float = 10):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


class _RateLimiter:
    def __init__(self):
        self._current: dict = {}
        self._previous: dict = {}
        self._lock = threading.Lock()

    @staticmethod
    def _extract_ip(addr: str) -> str:
        """Return just the host portion of an 'host:port' or plain address."""
        if not addr:
            return addr
        # IPv6 literal: [::1]:port
        if addr.startswith("["):
            end = addr.find("]")
            if end != -1:
                return addr[1:end]
        # IPv4 host:port
        if ":" in addr:
            return addr.rsplit(":", 1)[0]
        return addr

    def allow(self, addr: str) -> bool:
        ip = self._extract_ip(addr)

        with self._lock:
            if len(self._current) >= MAX_ENTRIES:
                self._rotate()

            if ip in self._current:
                return self._current[ip].allow()

            if ip in self._previous:
                limiter = self._previous[ip]
                self._current[ip] = limiter
                return limiter.allow()

            limiter = _TokenBucket()
            self._current[ip] = limiter
            return limiter.allow()

    def _rotate(self) -> None:
        # called under self._lock
        self._previous = self._current
        self._current = {}


_limiter = _RateLimiter()


def rate_limit_allow(addr: str) -> bool:
    """Return True if the request from *addr* should be allowed."""
    return _limiter.allow(addr)
