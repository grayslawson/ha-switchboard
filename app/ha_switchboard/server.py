"""Small standard-library HTTP server for the App and standalone image."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import stat
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlsplit

from .discovery import register_supervisor_discovery
from . import __version__
from .gateway import Gateway, GatewayConfig
from .contracts import error_envelope, validate_decision_payload
from .http_security import RateLimiter, validate_endpoint
from .handoff import HandoffBroker, HttpRouteAdapter, StaticRouteAdapter
from .jev_client import (
    DEFAULT_OPENROUTER_DECISIONS_ENDPOINT,
    DEFAULT_OPENROUTER_DECISIONS_MODEL,
    DEFAULT_TYPESAFE_ENDPOINT,
    DEFAULT_TYPESAFE_MODEL,
    HttpJevClient,
    OpenRouterDecisionsClient,
    StaticJevClient,
    TypeSafeJevClient,
)
from .openrouter_fallback import DEFAULT_ENDPOINT, OpenAICompatibleFallbackAdapter
from .protocol import Complexity, JevDecision, ModelRoute, PrivacyMode, ResponseKind, RouteKind
from .route_policy import RouteRegistry
from .store import PERSISTED_STATE_FILE_NAMES, ProfileStore
from .web import dashboard_html


_LOG = logging.getLogger("ha_switchboard")
_ORIGINAL_THREADING_HTTP_SERVER = ThreadingHTTPServer
_SUPERVISOR_DISCOVERY_RETRY_ATTEMPTS = 10
_SUPERVISOR_DISCOVERY_RETRY_DELAY_SECONDS = 30.0

from .limits import MAX_REQUEST_BYTES, MAX_REQUEST_WORKERS, REQUEST_READ_TIMEOUT


class RequestError(ValueError):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _log_field(value: Any) -> str:
    """Keep request-supplied values out of the Supervisor log."""

    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value))[:64]


def build_gateway(data_dir: str) -> Gateway:
    options = _migrate_options(_load_options(data_dir))
    warnings: list[str] = []
    if options.get("migration_warning") == "supervisor_read_only_migrated_to_adapter_only":
        warnings.append("supervisor_read_only_migrated_to_adapter_only")
    route_json = os.environ.get("JEV_ROUTE_REGISTRY", "")
    try:
        routes = RouteRegistry.from_dict(json.loads(route_json)) if route_json else RouteRegistry()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        routes = RouteRegistry()
        warnings.append("invalid_route_registry")
    adapter = StaticRouteAdapter({})
    fallback_provider = _env_or_option(options, "FALLBACK_PROVIDER", "fallback_provider", "disabled").lower()
    if fallback_provider not in {"disabled", "openrouter", "openai_compatible", "typed_http"}:
        warnings.append("invalid_fallback_provider")
        fallback_provider = "disabled"
    fallback_endpoint = (
        os.environ.get("FALLBACK_BASE_URL", "").strip()
        or os.environ.get("FALLBACK_ENDPOINT", "").strip()
        or _option_text(options, "fallback_base_url")
        or _option_text(options, "fallback_endpoint")
    )
    if fallback_provider == "disabled" and fallback_endpoint:
        fallback_provider = "openai_compatible" if (
            os.environ.get("FALLBACK_BASE_URL", "").strip() or _option_text(options, "fallback_base_url")
        ) else "typed_http"
    if fallback_provider != "disabled":
        fallback_key = os.environ.get("FALLBACK_API_KEY") or _option_text(options, "fallback_api_key")
        route_id = "configured-fallback"
        if fallback_provider == "openrouter":
            fallback_endpoint = fallback_endpoint or DEFAULT_ENDPOINT
        if fallback_provider in {"openrouter", "openai_compatible"}:
            fallback_model = os.environ.get("FALLBACK_MODEL", "").strip() or _option_text(options, "fallback_model")
            if not fallback_model:
                warnings.append("fallback_model_missing")
                fallback_provider = "disabled"
            else:
                try:
                    adapter = OpenAICompatibleFallbackAdapter(
                        base_url=fallback_endpoint,
                        model=fallback_model,
                        api_key=fallback_key,
                    )
                    hosted = adapter.hosted
                except (TypeError, ValueError):
                    warnings.append("invalid_fallback_endpoint")
                    fallback_provider = "disabled"
        else:
            if not fallback_endpoint:
                warnings.append("fallback_endpoint_missing")
                fallback_provider = "disabled"
            else:
                try:
                    validate_endpoint(fallback_endpoint)
                    hosted = HttpJevClient(fallback_endpoint).hosted
                    if hosted and urlsplit(fallback_endpoint).scheme != "https":
                        raise ValueError("hosted fallback endpoint must use HTTPS")
                    adapter = HttpRouteAdapter({route_id: fallback_endpoint}, api_keys={route_id: fallback_key})
                except (TypeError, ValueError):
                    warnings.append("invalid_fallback_endpoint")
                    fallback_provider = "disabled"
        if fallback_provider != "disabled":
            route = ModelRoute(
                route_id=route_id,
                kind=fallback_provider,
                response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
                complexity_ceiling=Complexity.REASONING,
                privacy_modes=(PrivacyMode.HOSTED_ALLOWED,) if hosted else tuple(PrivacyMode),
                latency_budget_ms=8_000,
                cost_ceiling=0.5,
            )
            routes = RouteRegistry(routes=(route,), revision="configured-fallback-1")
    jev_provider = _env_or_option(options, "JEV_PROVIDER", "jev_provider", "disabled").lower()
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip() or _option_text(options, "jev_endpoint")
    base_url = os.environ.get("JEV_BASE_URL", "").strip() or _option_text(options, "jev_base_url")
    api_key = os.environ.get("JEV_API_KEY") or _option_text(options, "jev_api_key")
    model = os.environ.get("JEV_MODEL", "").strip() or _option_text(options, "jev_model")
    if jev_provider == "disabled" and (endpoint or base_url):
        parsed = urlsplit(endpoint or base_url)
        jev_provider = (
            "openrouter"
            if parsed.hostname == "openrouter.ai" and parsed.path.rstrip("/") == "/api/alpha/decisions"
            else "compatible"
        )
    try:
        if jev_provider == "disabled":
            jev = StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE, reason="jev_not_configured"))
        elif jev_provider == "typesafe":
            jev = TypeSafeJevClient(endpoint or base_url or DEFAULT_TYPESAFE_ENDPOINT, api_key=api_key, model=model or DEFAULT_TYPESAFE_MODEL)
        elif jev_provider == "openrouter":
            jev = OpenRouterDecisionsClient(endpoint or DEFAULT_OPENROUTER_DECISIONS_ENDPOINT, api_key=api_key, model=model or DEFAULT_OPENROUTER_DECISIONS_MODEL)
        elif jev_provider == "compatible":
            if not endpoint and not base_url:
                raise ValueError("compatible Jev endpoint is required")
            validate_endpoint(endpoint or base_url)
            jev = HttpJevClient(endpoint or base_url, api_key=api_key)
        else:
            warnings.append("invalid_jev_provider")
            jev = StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE, reason="invalid_provider_configuration"))
    except (TypeError, ValueError):
        if jev_provider == "compatible":
            warnings.append("invalid_jev_endpoint")
        else:
            warnings.append("invalid_jev_configuration")
        jev = StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE, reason="invalid_provider_configuration"))
    try:
        privacy = PrivacyMode(_env_or_option(options, "PRIVACY_MODE", "privacy_mode", "local_only"))
    except ValueError:
        privacy = PrivacyMode.LOCAL_ONLY
        warnings.append("invalid_privacy_mode")
    gateway = Gateway(
        store=ProfileStore(data_dir),
        jev=jev,
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
        config=GatewayConfig(privacy_mode=privacy),
    )
    gateway.configuration_warnings = tuple(dict.fromkeys(warnings))
    if warnings:
        _LOG.warning(
            "event=configuration_degraded warning_count=%d warnings=%s",
            len(warnings), ",".join(_log_field(item) for item in gateway.configuration_warnings),
        )
        for warning in gateway.configuration_warnings:
            gateway.diagnostics.record(
                "configuration_warning",
                level="warning",
                outcome="degraded",
                warning=warning,
                summary="Configuration requires attention",
            )
    if not gateway._jev_configured():
        gateway.diagnostics.record(
            "provider_not_configured",
            level="warning",
            outcome="degraded",
            route_class="jev",
            summary="No Jev decision provider is configured",
        )
    return gateway


def _option_text(options: dict[str, Any], name: str, default: str = "") -> str:
    value = options.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _env_or_option(options: dict[str, Any], env_name: str, option_name: str, default: str = "") -> str:
    value = os.environ.get(env_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _option_text(options, option_name, default)


def _load_options(data_dir: str) -> dict[str, Any]:
    path = os.path.join(data_dir, "options.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _load_supervisor_options()
    return value if isinstance(value, dict) else _load_supervisor_options()


def _migrate_options(options: dict[str, Any]) -> dict[str, Any]:
    """Normalize historical options and fail closed on removed modes.

    Releases before explicit provider selection used ``jev_endpoint`` as a
    custom Switchboard decision endpoint and ``fallback_endpoint`` as a
    provider URL.  Preserve those values while making the wire contract
    explicit for new configurations.
    """

    migrated = dict(options)
    if migrated.get("gateway_mode") == "supervisor_read_only":
        migrated["gateway_mode"] = "adapter_only"
        migrated["migration_warning"] = "supervisor_read_only_migrated_to_adapter_only"
    if migrated.get("gateway_mode") not in {None, "adapter_only"}:
        raise ValueError("unsupported gateway mode")
    if migrated.get("jev_provider") in {None, "", "disabled"} and (
        isinstance(migrated.get("jev_endpoint"), str) and migrated["jev_endpoint"].strip()
    ):
        endpoint = migrated.get("jev_endpoint")
        parsed = urlsplit(endpoint) if isinstance(endpoint, str) else None
        if parsed and parsed.hostname == "openrouter.ai" and parsed.path.rstrip("/") == "/api/alpha/decisions":
            migrated["jev_provider"] = "openrouter"
        elif isinstance(endpoint, str) and endpoint.strip():
            migrated["jev_provider"] = "compatible"
        else:
            migrated["jev_provider"] = "disabled"
    if "fallback_base_url" not in migrated and "fallback_endpoint" in migrated:
        migrated["fallback_base_url"] = migrated.get("fallback_endpoint")
    if "fallback_endpoint" not in migrated and "fallback_base_url" in migrated:
        migrated["fallback_endpoint"] = migrated.get("fallback_base_url")
    if migrated.get("fallback_provider") in {None, "", "disabled"}:
        if isinstance(options.get("fallback_base_url"), str) and options["fallback_base_url"].strip():
            migrated["fallback_provider"] = "openai_compatible"
        elif isinstance(options.get("fallback_endpoint"), str) and options["fallback_endpoint"].strip():
            migrated["fallback_provider"] = "typed_http"
    return migrated


def _prepare_data_dir_and_drop_privileges(data_dir: str) -> None:
    """Prepare Supervisor's root-owned mount, then run as an unprivileged user.

    Only the directory owner changes. Supervisor's root-only options.json
    remains private and is read through the scoped self-info API instead.
    """

    if os.geteuid() != 0:
        return
    directory = os.lstat(data_dir)
    if not stat.S_ISDIR(directory.st_mode):
        raise RuntimeError("data path must be a directory, not a symlink")
    os.chown(data_dir, 65532, 65532)
    # Supervisor's options.json contains credentials and remains root-owned.
    # Only repair ownership for files written by ProfileStore, and reject
    # symlinks so a malformed mounted volume cannot redirect chown elsewhere.
    for name in PERSISTED_STATE_FILE_NAMES:
        path = os.path.join(data_dir, name)
        try:
            item = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
            raise RuntimeError(f"state path must be a regular file: {name}")
        os.chown(path, 65532, 65532)
    os.setgroups([])
    os.setgid(65532)
    os.setuid(65532)


def _retry_supervisor_discovery(
    port: int,
    gateway_token: str,
    *,
    attempts: int = _SUPERVISOR_DISCOVERY_RETRY_ATTEMPTS,
    delay_seconds: float = _SUPERVISOR_DISCOVERY_RETRY_DELAY_SECONDS,
) -> bool:
    """Retry discovery for a bounded window after a startup-ordering race."""

    delay = threading.Event()
    max_attempts = max(1, min(int(attempts), 20))
    interval = max(0.0, min(float(delay_seconds), 300.0))
    for _attempt in range(max_attempts):
        delay.wait(interval)
        if register_supervisor_discovery(port=port, gateway_token=gateway_token):
            return True
    _LOG.warning(
        "event=supervisor_discovery_failed attempts=%d retry_window_seconds=%d",
        max_attempts,
        int(max_attempts * interval),
    )
    return False


def _load_supervisor_options() -> dict[str, Any]:
    """Read this App's options without requiring a root-owned file mount.

    Supervisor protects ``/data/options.json`` as root-only. That is
    incompatible with the App's unprivileged runtime user, so the App uses
    its scoped Supervisor token to read the same self-only options endpoint.
    Standalone images have no token and simply fall back to environment
    configuration.
    """

    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        return {}
    base_url = (os.environ.get("SUPERVISOR") or "http://supervisor").rstrip("/")
    request = Request(
        f"{base_url}/addons/self/info",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read(64_000))
    except (HTTPError, OSError, TimeoutError, URLError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    options = data.get("options") if isinstance(data, dict) else None
    return options if isinstance(options, dict) else {}


def safe_app_status(options: dict[str, Any], *, ingress_only: bool, gateway: Gateway) -> dict[str, Any]:
    """Return dashboard-safe App settings; never serialize credentials or URLs."""

    status = {
        "version": __version__,
        "gateway_mode": _option_text(options, "gateway_mode", "adapter_only") or "adapter_only",
        "ingress_only": bool(ingress_only),
        "privacy_mode": _option_text(options, "privacy_mode", "local_only") or "local_only",
        "profile_refresh_minutes": _safe_refresh_minutes(options.get("profile_refresh_minutes")),
        "auth_configured": bool(getattr(gateway, "gateway_token", "")),
        "fallback_provider": str(options.get("fallback_provider") or "disabled"),
        "fallback_configured": bool(getattr(getattr(gateway, "routes", None), "routes", ())),
    }
    warnings = list(getattr(gateway, "configuration_warnings", ()))
    if warnings:
        status["configuration_warnings"] = warnings
    return status


def _safe_refresh_minutes(value: Any) -> int:
    try:
        parsed = int(value) if value is not None else 15
    except (TypeError, ValueError):
        return 15
    return max(1, min(parsed, 1440))


class GatewayHandler(BaseHTTPRequestHandler):
    gateway: Gateway
    ingress_only: bool = True
    app_status: dict[str, Any] = {}
    rate_limiter = RateLimiter()

    server_version = f"ha-switchboard/{__version__}"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_READ_TIMEOUT)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            return
        path = self.path.split("?", 1)[0]
        if path in {"", "/"}:
            self._write_html(dashboard_html())
        elif path == "/healthz":
            self._write(200, self.gateway.health())
        elif path == "/readyz":
            body = self.gateway.ready()
            self._write(200 if body["status"] == "ready" else 503, body)
        elif path == "/v1/profile/status":
            self._write(200, self.gateway.profile_status())
        elif path == "/v1/app/status":
            self._write(200, self.app_status)
        elif path == "/v1/provider/status":
            self._write(200, self.gateway.provider_status())
        elif path == "/v1/diagnostics":
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=False)
            def query_value(name: str) -> str | None:
                values = query.get(name, [])
                return values[0] if values else None
            try:
                page = int(query_value("page") or "1")
                limit = int(query_value("limit") or "20")
            except ValueError:
                raise RequestError(400, "invalid_request") from None
            try:
                body = self.gateway.diagnostics_page(
                    page=page,
                    limit=limit,
                    level=query_value("level"),
                    event_type=query_value("event_type"),
                    correlation_id=query_value("correlation_id"),
                    route_class=query_value("route_class"),
                    outcome=query_value("outcome"),
                )
            except ValueError:
                self._write(400, error_envelope("invalid_request"))
            else:
                self._write(200, body)
        else:
            self._write(404, {"error": {"code": "not_found"}})

    def do_PUT(self) -> None:  # noqa: N802
        self._write(405, error_envelope("method_not_allowed"))

    do_PATCH = do_PUT
    do_DELETE = do_PUT

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        trace = uuid.uuid4().hex[:12]
        started = time.monotonic()
        if not self._authorized():
            _LOG.warning("request trace=%s event=auth_denied path=%s", trace, _log_field(self.path.split("?", 1)[0]))
            return
        if not self.rate_limiter.allow(self.client_address[0]):
            self._write(429, error_envelope("rate_limited"))
            return
        if self.path.split("?", 1)[0] == "/v1/app/status":
            self._write(404, {"error": {"code": "not_found"}})
            return
        try:
            payload = self._read_json()
            path = self.path.split("?", 1)[0]
            if path == "/v1/profile/scan":
                status = self.gateway.invalidate({"kind": "manual_reconcile"})
                _LOG.info("request trace=%s event=scan_requested status=%s", trace, _log_field(status.get("status")))
                self._write(202, {"status": "scan_requested"})
            elif path == "/v1/profile/reconcile":
                snapshot = payload.get("snapshot")
                if not isinstance(snapshot, dict):
                    raise ValueError("snapshot is required")
                status = self.gateway.reconcile(snapshot)
                _LOG.info(
                    "request trace=%s event=profile_reconciled status=%s capabilities=%s",
                    trace, _log_field(status.get("status")), status.get("capability_count", 0),
                )
                self._write(200, status)
            elif path == "/v1/profile/invalidate":
                status = self.gateway.invalidate(payload)
                _LOG.info("request trace=%s event=profile_invalidated status=%s", trace, _log_field(status.get("status")))
                self._write(200, status)
            elif path == "/v1/provider/compatibility":
                probe = payload.get("probe", True)
                if not isinstance(probe, bool):
                    raise ValueError("probe must be boolean")
                status = self.gateway.provider_compatibility(probe=probe)
                _LOG.info(
                    "request trace=%s event=provider_compatibility status=%s",
                    trace, _log_field(status.get("status")),
                )
                self._write(200, status)
            elif path == "/v1/assist/process":
                validate_decision_payload(payload)
                result = self.gateway.process(payload)
                _LOG.info(
                    "request trace=%s event=decision kind=%s code=%s confidence=%s duration_ms=%d",
                    trace, _log_field(result.kind.value), _log_field(result.response_key),
                    f"{result.confidence:.3f}" if result.confidence is not None else "none",
                    round((time.monotonic() - started) * 1000),
                )
                self._write(200, result.to_dict())
            else:
                self._write(404, {"error": {"code": "not_found"}})
        except RequestError as exc:
            _LOG.warning("request trace=%s event=%s path=%s", trace, exc.code, _log_field(self.path.split("?", 1)[0]))
            self._write(exc.status, error_envelope(exc.code))
        except ValueError:
            _LOG.warning("request trace=%s event=invalid_request path=%s", trace, _log_field(self.path.split("?", 1)[0]))
            self._write(400, {"error": {"code": "invalid_request", "message": "request was invalid"}})
        except Exception as exc:
            _LOG.error("request trace=%s event=internal_error path=%s error_type=%s", trace, _log_field(self.path.split("?", 1)[0]), type(exc).__name__)
            self._write(500, error_envelope("internal_error"))

    def log_message(self, format: str, *args: Any) -> None:
        # The event logger records bounded outcomes without headers, bodies, or query strings.
        return

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise ValueError("request body length is invalid") from None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise RequestError(413, "request_too_large")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        # A real HTTP request always has ``command``. Keeping the direct
        # helper seam permissive preserves callers that exercise JSON parsing
        # without constructing a socket handler.
        if content_type != "application/json" and hasattr(self, "command"):
            raise RequestError(415, "unsupported_media_type")
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(8192, remaining))
            if not chunk:
                raise ValueError("request body ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _authorized(self) -> bool:
        path = self.path.split("?", 1)[0]
        from_ingress = self.client_address[0] == "172.30.32.2"

        if not self._browser_origin_allowed(path):
            self._write(403, {"error": {"code": "cross_origin_request_forbidden"}})
            return False

        # Health endpoints intentionally remain unauthenticated.  They expose
        # only bounded liveness/readiness facts and are needed by Supervisor,
        # container health checks, and local diagnostics.
        if path in {"/healthz", "/readyz"}:
            return True

        # The browser UI is an ingress surface.  Do not turn a bearer token
        # into a second way to expose the UI outside Supervisor.
        if path in {"", "/"} or path.startswith("/static/"):
            if from_ingress:
                return True
            self._write(403, {"error": {"code": "ingress_source_forbidden"}})
            return False

        # Supervisor ingress is already authenticated by Home Assistant and
        # may call the protected API without duplicating the gateway token.
        if from_ingress:
            return True

        expected = getattr(self.gateway, "gateway_token", "")
        if not expected:
            self._write(401, {"error": {"code": "gateway_token_required"}})
            return False
        supplied = self.headers.get("Authorization", "")
        if supplied == f"Bearer {expected}":
            return True
        if self.ingress_only:
            # Preserve an explicit error for direct, unauthenticated API
            # requests while still allowing the Core integration's matching
            # bearer token through the ingress-only default.
            self._write(401, {"error": {"code": "unauthorized"}})
            return False
        self._write(401, {"error": {"code": "unauthorized"}})
        return False

    def _browser_origin_allowed(self, path: str) -> bool:
        """Reject browser cross-site mutations without constraining Supervisor clients.

        Supervisor/Core clients do not need an Origin header.  Browsers that
        issue cross-origin POSTs provide Fetch Metadata, while same-origin HA
        dashboard fetches report ``same-origin``.  Legacy/non-browser callers
        with no browser metadata remain compatible with the ingress contract.
        """

        if getattr(self, "command", "") != "POST" or not path.startswith("/v1/"):
            return True
        fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        origin = self.headers.get("Origin", "").strip().lower()
        if fetch_site in {"cross-site", "same-site", "none"} or origin == "null":
            _LOG.warning("event=csrf_rejected reason=cross_origin_metadata")
            return False
        return True

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            _LOG.debug("event=response_client_disconnected content_type=json")

    def _write_html(self, raw: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            _LOG.debug("event=response_client_disconnected content_type=html")


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Keep slow clients from exhausting Supervisor ingress worker threads."""

    daemon_threads = True

    def __init__(self, *args: Any, max_workers: int = MAX_REQUEST_WORKERS, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._worker_slots = threading.BoundedSemaphore(max_workers)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="HA Switchboard gateway")
    parser.add_argument("--data-dir", default="/data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    _prepare_data_dir_and_drop_privileges(args.data_dir)
    gateway = build_gateway(args.data_dir)
    options = _migrate_options(_load_options(args.data_dir))
    gateway.gateway_token = os.environ.get("GATEWAY_TOKEN", "") or str(options.get("gateway_token", ""))
    ingress_only_value = os.environ.get("HA_SWITCHBOARD_INGRESS_ONLY")
    if ingress_only_value is None:
        ingress_only = bool(options.get("ingress_only", True))
    else:
        ingress_only = ingress_only_value.strip().lower() not in {"0", "false", "no", "off"}
    handler = type(
        "ConfiguredGatewayHandler",
        (GatewayHandler,),
        {
            "gateway": gateway,
            "ingress_only": ingress_only,
            "app_status": safe_app_status(options, ingress_only=ingress_only, gateway=gateway),
        },
    )
    server_type = (
        BoundedThreadingHTTPServer
        if ThreadingHTTPServer is _ORIGINAL_THREADING_HTTP_SERVER
        else ThreadingHTTPServer
    )
    server = server_type((args.host, args.port), handler)
    announced = register_supervisor_discovery(port=args.port, gateway_token=gateway.gateway_token)
    if not announced and os.environ.get("SUPERVISOR_TOKEN", "").strip():
        threading.Thread(
            target=_retry_supervisor_discovery,
            args=(args.port, gateway.gateway_token),
            daemon=True,
            name="switchboard-discovery-retry",
        ).start()
    _LOG.info(
        "event=gateway_started host=%s port=%d jev_client=%s privacy=%s profile_status=%s",
        args.host, args.port, type(gateway.jev).__name__, gateway.config.privacy_mode.value,
        _log_field(gateway.profile_status().get("status")),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
