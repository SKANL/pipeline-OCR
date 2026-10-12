"""In-memory token-bucket rate limiting per client.

Client key: verified bearer email, else the peer IP (`request.client.host`).
`X-Forwarded-For` is trusted only with `TRUST_PROXY_HEADERS=true` (set it on
Render, which sits behind a proxy); then the left-most address is used.

ponytail: per-instance memory; limits multiply with instances and reset on
restart. Move buckets to Mongo/Redis if the API runs on more than one instance.
"""

from __future__ import annotations

import math
import threading
import time

from fastapi import HTTPException, Request

from app.config import get_settings
from app.security import bearer_email

_MAX_KEYS = 10_000  # ponytail: crude memory bound; buckets are dropped wholesale past it


class TokenBucket:
    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, capacity: int, period: float, now: float | None = None) -> float:
        """Take one token; return 0 when allowed, else seconds until the next token."""
        now = time.monotonic() if now is None else now
        rate = capacity / period
        with self._lock:
            if key not in self._state and len(self._state) >= _MAX_KEYS:
                # ponytail: O(n) eviction of the stalest key, only when the map is full.
                del self._state[min(self._state, key=lambda k: self._state[k][1])]
            tokens, last = self._state.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * rate)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                return 0.0
            self._state[key] = (tokens, now)
            return (1 - tokens) / rate

    def clear(self) -> None:
        with self._lock:
            self._state.clear()


_search, _write = TokenBucket(), TokenBucket()


def reset() -> None:
    _search.clear()
    _write.clear()


def client_key(request: Request) -> str:
    try:
        email = bearer_email(request)
    except HTTPException:
        email = None  # invalid token: limit by IP; auth rejects it later
    if email:
        return f"user:{email}"
    if get_settings().trust_proxy_headers:
        # The trusted proxy appends the real peer last; earlier entries are client-supplied.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return f"ip:{forwarded}"
    return f"ip:{request.client.host if request.client else 'desconocido'}"


def _limit(bucket: TokenBucket, per_minute: int, request: Request) -> None:
    wait = bucket.take(client_key(request), per_minute, 60.0)
    if wait:
        raise HTTPException(429, "Demasiadas solicitudes; intenta más tarde.",
                            headers={"Retry-After": str(max(1, math.ceil(wait)))})


def limit_search(request: Request) -> None:
    _limit(_search, get_settings().rate_limit_search_per_min, request)


def limit_write(request: Request) -> None:
    _limit(_write, get_settings().rate_limit_write_per_min, request)
