"""Network policy helpers used by provider and gateway HTTP boundaries."""

from __future__ import annotations

import re
import math
import time
from collections import defaultdict, deque
from ipaddress import ip_address
from threading import Lock
import urllib.request
from urllib.parse import parse_qsl, urlsplit

from .limits import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS


_SENSITIVE_QUERY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "password",
        "secret",
        "token",
    }
)


def validate_endpoint(endpoint: str, *, allow_http_local: bool = True) -> str:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 2_048:
        raise ValueError("endpoint is missing or too long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in endpoint) or re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", endpoint.casefold()):
        raise ValueError("endpoint contains control characters")
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("endpoint must be an absolute HTTP(S) URL without userinfo")
    if parsed.fragment:
        raise ValueError("endpoint must not contain a fragment")
    # Credentials in query strings are routinely copied into logs and browser
    # history. Provider credentials belong in headers/options, never URLs.
    query_names = {name.casefold() for name, _value in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_names & _SENSITIVE_QUERY_NAMES:
        raise ValueError("endpoint must not contain credential query parameters")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint port is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("endpoint port is invalid")
    host = parsed.hostname.lower()
    local = host in {"localhost", "supervisor"} or host.endswith(".local")
    try:
        local = local or ip_address(host).is_private or ip_address(host).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not (allow_http_local and local):
        raise ValueError("remote endpoint must use HTTPS")
    return endpoint


def request_timeout(value: float, *, minimum: float = 0.2, maximum: float = 30.0) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout is out of bounds")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout is out of bounds") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError("timeout is out of bounds")
    return value


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent a provider from redirecting a credential-bearing request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def open_without_redirect(request: urllib.request.Request, *, timeout: float):
    """Open one bounded request without forwarding headers to another host."""

    return urllib.request.build_opener(NoRedirectHandler()).open(
        request,
        timeout=request_timeout(timeout),
    )


class RetryPolicy:
    """Bounded exponential backoff for idempotent provider reads.

    The policy only calculates whether a retry is permitted and its delay. It
    never retries Home Assistant service execution, and callers remain in
    control of the actual sleep/transport operation.
    """

    def __init__(self, *, attempts: int = 2, base_delay: float = 0.25, max_delay: float = 2.0) -> None:
        if not 0 <= attempts <= 5:
            raise ValueError("retry attempts are out of bounds")
        if base_delay < 0 or max_delay < base_delay or max_delay > 30:
            raise ValueError("retry delays are out of bounds")
        self.attempts = attempts
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)

    def can_retry(self, attempt: int, *, idempotent: bool = True) -> bool:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            return False
        return bool(idempotent and attempt < self.attempts)

    def delay(self, attempt: int) -> float:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            raise ValueError("retry attempt is invalid")
        return min(self.max_delay, self.base_delay * (2 ** attempt))


class CircuitBreaker:
    """Small thread-safe provider circuit with closed/open/half-open states."""

    def __init__(self, *, failure_threshold: int = 3, cooldown: float = 30.0) -> None:
        if not 1 <= failure_threshold <= 20 or cooldown <= 0 or cooldown > 900:
            raise ValueError("circuit bounds are invalid")
        self.failure_threshold = failure_threshold
        self.cooldown = float(cooldown)
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = Lock()

    def allow(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if self._opened_at is None:
                return True
            if current - self._opened_at < self.cooldown:
                return False
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._probe_in_flight = False
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = current
            return self._opened_at is not None

    def state(self, *, now: float | None = None) -> str:
        current = time.monotonic() if now is None else now
        with self._lock:
            if self._opened_at is None:
                return "closed"
            return "half_open" if current - self._opened_at >= self.cooldown else "open"


class RateLimiter:
    def __init__(self, *, limit: int = RATE_LIMIT_REQUESTS, window: float = RATE_LIMIT_WINDOW_SECONDS) -> None:
        if limit < 1 or window <= 0:
            raise ValueError("invalid rate limit")
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and current - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(current)
        return True
