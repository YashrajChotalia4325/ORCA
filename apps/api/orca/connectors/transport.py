"""HTTP transport layer: LIVE (with cache / retries / circuit breaker / optional
recording), REPLAY (recorded real responses) and DEMO (synthetic scenario).

Connectors build requests and parse responses; they never know which
transport is underneath. This is what guarantees that the *same* agent code
runs in all three modes, and that the mode is carried into every
provenance record.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

from ..core.clock import parse_utc, utcnow
from ..core.schemas.common import DataMode
from .health import HEALTH

STALE_IF_ERROR_S = 24 * 3600


@dataclass
class FetchResult:
    data: Any
    url: str
    retrieved_at: datetime
    from_cache: bool
    latency_ms: float
    mode: DataMode
    stale_fallback: bool = False


class TransportError(Exception):
    def __init__(self, source_id: str, status: str, message: str):
        super().__init__(f"{source_id}: {status}: {message}")
        self.source_id = source_id
        self.status = status
        self.message = message


def request_key(url: str, params: dict | None) -> str:
    items = sorted((k, str(v)) for k, v in (params or {}).items())
    return f"{url}?{urlencode(items)}" if items else url


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def sanitize_url(url: str, params: dict | None, secret_keys: tuple[str, ...] = ("token", "key", "apikey", "password")) -> str:
    clean = {k: ("***" if k.lower() in secret_keys else v) for k, v in (params or {}).items()}
    return request_key(url, clean)


class Transport(ABC):
    mode: DataMode

    @abstractmethod
    async def get_json(self, source_id: str, url: str, params: dict | None = None, *,
                       ttl_s: int = 900, timeout_s: float | None = None, retries: int = 2,
                       headers: dict | None = None, parse: str = "json") -> FetchResult: ...

    async def aclose(self) -> None:  # pragma: no cover
        pass


class _TTLCache:
    def __init__(self, max_items: int = 2000):
        self._d: dict[str, tuple[float, datetime, Any]] = {}
        self._max = max_items

    def get(self, key: str) -> Optional[tuple[float, datetime, Any]]:
        return self._d.get(key)

    def put(self, key: str, retrieved_at: datetime, data: Any) -> None:
        if len(self._d) >= self._max:
            oldest = min(self._d, key=lambda k: self._d[k][0])
            self._d.pop(oldest, None)
        self._d[key] = (time.monotonic(), retrieved_at, data)


class LiveTransport(Transport):
    mode = DataMode.LIVE

    def __init__(self, user_agent: str, timeout_s: float = 15.0, recorder: "Recorder | None" = None):
        self._client = httpx.AsyncClient(headers={"User-Agent": user_agent}, follow_redirects=True,
                                         timeout=timeout_s, limits=httpx.Limits(max_connections=20))
        self._timeout = timeout_s
        self._cache = _TTLCache()
        self._inflight: dict[str, asyncio.Future] = {}
        self.recorder = recorder

    async def get_json(self, source_id, url, params=None, *, ttl_s=900, timeout_s=None, retries=2, headers=None,
                       parse="json"):
        key = request_key(url, params)
        clean = sanitize_url(url, params)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl_s:
            HEALTH.cache_hit(source_id)
            res = FetchResult(cached[2], clean, cached[1], True, 0.0, self.mode)
            if self.recorder:
                self.recorder.save(source_id, key, res)
            return res
        # request coalescing: concurrent agents asking for the same URL share one call
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            res = await self._fetch(source_id, url, params, key, clean, timeout_s, retries, headers, cached, parse)
            fut.set_result(res)
            return res
        except Exception as e:
            fut.set_exception(e)
            fut.exception()  # mark retrieved
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch(self, source_id, url, params, key, clean, timeout_s, retries, headers, cached, parse="json"):
        health = HEALTH.get(source_id)
        if not health.breaker.allow():
            return self._fallback(source_id, key, clean, cached,
                                  TransportError(source_id, "CIRCUIT_OPEN", "circuit breaker open after repeated failures"))
        last_exc: TransportError | None = None
        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            try:
                r = await self._client.get(url, params=params, timeout=timeout_s or self._timeout, headers=headers)
                latency = (time.perf_counter() - t0) * 1000
                if r.status_code >= 500 or r.status_code == 429:
                    raise TransportError(source_id, f"HTTP_{r.status_code}", r.text[:200])
                if r.status_code >= 400:
                    # client errors are not retried
                    HEALTH.failure(source_id, f"HTTP_{r.status_code}: {r.text[:200]}")
                    raise TransportError(source_id, f"HTTP_{r.status_code}", r.text[:300])
                data = r.json() if parse == "json" else r.text
                now = utcnow()
                self._cache.put(key, now, data)
                HEALTH.success(source_id, latency)
                res = FetchResult(data, clean, now, False, latency, self.mode)
                if self.recorder:
                    self.recorder.save(source_id, key, res)
                return res
            except TransportError as e:
                if e.status.startswith("HTTP_4") and e.status != "HTTP_429":
                    raise
                last_exc = e
            except httpx.TimeoutException:
                last_exc = TransportError(source_id, "TIMEOUT", f"no response within {timeout_s or self._timeout:.0f}s")
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
                last_exc = TransportError(source_id, "NETWORK", f"{type(e).__name__}: {e}"[:200])
            HEALTH.failure(source_id, str(last_exc))
            if attempt < retries:
                await asyncio.sleep(0.4 * (2 ** attempt))
        return self._fallback(source_id, key, clean, cached, last_exc)

    def _fallback(self, source_id, key, clean, cached, exc: TransportError | None) -> FetchResult:
        if cached and (utcnow() - cached[1]).total_seconds() < STALE_IF_ERROR_S:
            HEALTH.cache_hit(source_id, stale=True)
            return FetchResult(cached[2], clean, cached[1], True, 0.0, self.mode, stale_fallback=True)
        raise exc or TransportError(source_id, "UNKNOWN", "request failed")

    async def aclose(self) -> None:
        await self._client.aclose()


class Recorder:
    """Persists real LIVE responses so they can be replayed later with their original timestamps."""

    def __init__(self, snapshot_dir: Path, description: str = ""):
        self.dir = snapshot_dir
        (self.dir / "responses").mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        self.index: dict[str, dict] = json.loads(self.index_path.read_text("utf-8")) if self.index_path.exists() else {}
        self.manifest_path = self.dir / "manifest.json"
        if not self.manifest_path.exists():
            self.manifest_path.write_text(json.dumps({
                "recorded_at": utcnow().isoformat(), "description": description,
                "note": "Real responses from public endpoints recorded by ORCA LIVE transport.",
            }, indent=2), "utf-8")

    def save(self, source_id: str, key: str, res: FetchResult) -> None:
        h = key_hash(key)
        fname = f"{source_id}_{h}.json"
        (self.dir / "responses" / fname).write_text(json.dumps(res.data, separators=(",", ":")), "utf-8")
        self.index[key] = {"file": fname, "source_id": source_id, "url": res.url,
                           "retrieved_at": res.retrieved_at.isoformat()}
        self.index_path.write_text(json.dumps(self.index, indent=1), "utf-8")


class ReplayTransport(Transport):
    mode = DataMode.REPLAY

    def __init__(self, snapshot_dir: Path):
        self.dir = snapshot_dir
        self.index: dict[str, dict] = json.loads((snapshot_dir / "index.json").read_text("utf-8"))
        self.manifest = json.loads((snapshot_dir / "manifest.json").read_text("utf-8"))
        self.recorded_at = parse_utc(self.manifest["recorded_at"])

    async def get_json(self, source_id, url, params=None, *, ttl_s=900, timeout_s=None, retries=2, headers=None,
                       parse="json"):
        key = request_key(url, params)
        entry = self.index.get(key)
        if entry is None:
            HEALTH.failure(source_id, "request not present in replay recording", mode="REPLAY")
            raise TransportError(source_id, "NOT_IN_RECORDING",
                                 "this request was not captured in the replay snapshot")
        data = json.loads((self.dir / "responses" / entry["file"]).read_text("utf-8"))
        HEALTH.success(source_id, 0.0, mode="REPLAY")
        return FetchResult(data, entry["url"], parse_utc(entry["retrieved_at"]), False, 0.0, self.mode)


class DemoTransport(Transport):
    """Routes requests to a synthetic scenario. Output is always SIMULATED."""
    mode = DataMode.DEMO

    def __init__(self, responder: Callable[[str, str, dict], Any], now: Callable[[], datetime]):
        self._respond = responder
        self._now = now

    async def get_json(self, source_id, url, params=None, *, ttl_s=900, timeout_s=None, retries=2, headers=None,
                       parse="json"):
        t0 = time.perf_counter()
        await asyncio.sleep(0.05)  # keep event ordering realistic for the UI
        try:
            data = self._respond(source_id, url, dict(params or {}))
        except TransportError as e:
            HEALTH.failure(source_id, e.message, mode="DEMO")
            raise
        HEALTH.success(source_id, (time.perf_counter() - t0) * 1000, mode="DEMO")
        return FetchResult(data, request_key(url, params), self._now() - timedelta(seconds=40), False,
                           (time.perf_counter() - t0) * 1000, self.mode)
