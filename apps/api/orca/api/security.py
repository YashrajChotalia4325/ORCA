"""Authentication, authorisation and rate limiting.

* Bearer tokens map to roles via ORCA_API_TOKENS="tok1:authority,tok2:admin".
* With ORCA_AUTH_REQUIRED=false (development default) anonymous callers get role 'public'.
* Admin-only endpoints (probing all sources, evaluation runs, recording) require role 'admin'
  when auth is required.
* Token-bucket rate limit per client for expensive endpoints.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from ..config import get_settings


@dataclass
class Principal:
    role: str
    authenticated: bool
    client: str


def principal(request: Request) -> Principal:
    s = get_settings()
    auth = request.headers.get("authorization", "")
    client = request.client.host if request.client else "unknown"
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        role = s.api_tokens.get(tok)
        if role:
            return Principal(role=role, authenticated=True, client=client)
        raise HTTPException(status_code=401, detail="invalid token")
    if s.auth_required:
        raise HTTPException(status_code=401, detail="authentication required")
    return Principal(role="public", authenticated=False, client=client)


def require_admin(p: Principal = Depends(principal)) -> Principal:
    if get_settings().auth_required and p.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return p


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key: str, per_min: int) -> None:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(per_min), now))
        tokens = min(float(per_min), tokens + (now - last) * per_min / 60.0)
        if tokens < 1.0:
            raise HTTPException(status_code=429, detail="rate limit exceeded — try again shortly",
                                headers={"Retry-After": "10"})
        self._buckets[key] = (tokens - 1.0, now)


LIMITER = RateLimiter()


def rate_limited(p: Principal = Depends(principal)) -> Principal:
    LIMITER.check(p.client, get_settings().rate_limit_per_min)
    return p
