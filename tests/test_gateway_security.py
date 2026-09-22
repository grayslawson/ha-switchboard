from __future__ import annotations

from io import BytesIO
from urllib.request import Request
from types import SimpleNamespace

from ha_switchboard.http_security import (
    CircuitBreaker,
    RateLimiter,
    RetryPolicy,
    open_without_redirect,
    validate_endpoint,
)
from ha_switchboard.server import GatewayHandler


def test_endpoint_policy_rejects_remote_plain_http_and_userinfo() -> None:
    validate_endpoint("http://supervisor/api")
    try:
        validate_endpoint("http://provider.example/api")
    except ValueError:
        pass
    else:
        raise AssertionError("remote HTTP must be rejected")
    try:
        validate_endpoint("https://user:pass@provider.example/api")
    except ValueError:
        pass
    else:
        raise AssertionError("userinfo must be rejected")
    for endpoint in (
        "https://provider.example/api?api_key=leak",
        "https://provider.example/%0a",
        "https://provider.example:99999/api",
    ):
        try:
            validate_endpoint(endpoint)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe endpoint was accepted")


def test_rate_limiter_bounds_requests() -> None:
    limiter = RateLimiter(limit=2, window=10)
    assert limiter.allow("client", now=0)
    assert limiter.allow("client", now=1)
    assert not limiter.allow("client", now=2)
    assert limiter.allow("client", now=11)


def test_retry_policy_is_bounded_and_never_retries_non_idempotent_work() -> None:
    policy = RetryPolicy(attempts=2, base_delay=0.5, max_delay=0.75)
    assert policy.can_retry(0)
    assert policy.delay(0) == 0.5
    assert policy.delay(1) == 0.75
    assert not policy.can_retry(2)
    assert not policy.can_retry(0, idempotent=False)


def test_redirect_policy_uses_a_bounded_timeout_and_never_follows_redirects(monkeypatch) -> None:
    calls = []

    class FakeOpener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, timeout))
            return "response"

    monkeypatch.setattr("urllib.request.build_opener", lambda _handler: FakeOpener())
    assert open_without_redirect(Request("https://provider.example/decide"), timeout=2.0) == "response"
    assert calls == [("https://provider.example/decide", 2.0)]


def test_circuit_breaker_opens_and_allows_one_half_open_probe() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown=10)
    assert breaker.allow(now=0)
    assert not breaker.record_failure(now=0)
    assert breaker.record_failure(now=1)
    assert breaker.state(now=1) == "open"
    assert not breaker.allow(now=5)
    assert breaker.allow(now=11)
    assert breaker.state(now=11) == "half_open"
    assert not breaker.allow(now=11)
    breaker.record_success()
    assert breaker.state(now=11) == "closed"


def test_real_body_parser_requires_json_content_type() -> None:
    handler = object.__new__(GatewayHandler)
    handler.headers = {"Content-Length": "2", "Content-Type": "text/plain"}
    handler.rfile = BytesIO(b"{}")
    handler.command = "POST"
    handler._write = lambda *_args: None
    try:
        handler._read_json()
    except ValueError as exc:
        assert "unsupported_media_type" in str(exc)
    else:
        raise AssertionError("non-JSON content must be rejected")
