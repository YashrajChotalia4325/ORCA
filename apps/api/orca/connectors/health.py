"""Per-source health metrics and circuit breakers."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..core.clock import utcnow


@dataclass
class CircuitBreaker:
    fail_threshold: int = 3
    cooldown_s: float = 60.0
    state: str = "CLOSED"           # CLOSED | OPEN | HALF_OPEN
    consecutive_failures: int = 0
    opened_at: float = 0.0

    def allow(self) -> bool:
        if self.state == "OPEN":
            if time.monotonic() - self.opened_at >= self.cooldown_s:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.state = "CLOSED"
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.state == "HALF_OPEN" or self.consecutive_failures >= self.fail_threshold:
            self.state = "OPEN"
            self.opened_at = time.monotonic()


@dataclass
class SourceHealth:
    source_id: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    cache_hits: int = 0
    stale_served: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    def snapshot(self) -> dict:
        lat = sorted(self.latencies_ms)
        p50 = lat[len(lat) // 2] if lat else None
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None
        return {
            "source_id": self.source_id, "calls": self.calls, "successes": self.successes,
            "failures": self.failures, "cache_hits": self.cache_hits, "stale_served": self.stale_served,
            "success_rate": (self.successes / self.calls) if self.calls else None,
            "last_success": self.last_success, "last_failure": self.last_failure,
            "last_error": self.last_error, "latency_p50_ms": p50, "latency_p95_ms": p95,
            "circuit": self.breaker.state, "consecutive_failures": self.breaker.consecutive_failures,
        }


class HealthRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, SourceHealth] = {}

    def get(self, source_id: str, mode: str = "LIVE") -> SourceHealth:
        key = f"{mode}:{source_id}"
        with self._lock:
            if key not in self._by_key:
                self._by_key[key] = SourceHealth(source_id)
            return self._by_key[key]

    def success(self, source_id: str, latency_ms: float, mode: str = "LIVE") -> None:
        h = self.get(source_id, mode)
        h.calls += 1
        h.successes += 1
        h.last_success = utcnow()
        h.latencies_ms.append(latency_ms)
        h.breaker.record_success()

    def failure(self, source_id: str, error: str, mode: str = "LIVE") -> None:
        h = self.get(source_id, mode)
        h.calls += 1
        h.failures += 1
        h.last_failure = utcnow()
        h.last_error = error[:300]
        h.breaker.record_failure()

    def cache_hit(self, source_id: str, mode: str = "LIVE", stale: bool = False) -> None:
        h = self.get(source_id, mode)
        h.cache_hits += 1
        if stale:
            h.stale_served += 1

    def all(self, mode: str = "LIVE") -> dict[str, dict]:
        with self._lock:
            return {k.split(":", 1)[1]: v.snapshot() for k, v in self._by_key.items() if k.startswith(mode + ":")}


HEALTH = HealthRegistry()
