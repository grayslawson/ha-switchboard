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
from urllib.parse import urlsplit

from .discovery import register_supervisor_discovery
from . import __version__
from .gateway import Gateway, GatewayConfig
from .handoff import HandoffBroker, HttpRouteAdapter, StaticRouteAdapter
from .jev_client import HttpJevClient, OpenRouterDecisionsClient, client_from_environment
from .openrouter_fallback import DEFAULT_ENDPOINT, OpenRouterFallbackAdapter
from .protocol import Complexity, ModelRoute, PrivacyMode, ResponseKind
from .route_policy import RouteRegistry
from .store import ProfileStore
from .web import dashboard_html


_LOG = logging.getLogger("ha_switchboard")
_ORIGINAL_THREADING_HTTP_SERVER = ThreadingHTTPServer

MAX_REQUEST_BYTES = 64_000
REQUEST_READ_TIMEOUT = 10.0
MAX_REQUEST_WORKERS = 32


def _log_field(value: Any) -> str:
    """Keep request-supplied values out of the Supervisor log."""

    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value))[:64]


def build_gateway(data_dir: str) -> Gateway:
    options = _load_options(data_dir)
    route_json = os.environ.get("JEV_ROUTE_REGISTRY", "")
    routes = RouteRegistry.from_dict(json.loads(route_json)) if route_json else RouteRegistry()
    adapter = StaticRouteAdapter({})
    fallback_provider = os.environ.get("FALLBACK_PROVIDER", "").strip() or str(options.get("fallback_provider", "disabled"))
    if fallback_provider not in {"disabled", "openrouter", "typed_http"}:
        raise ValueError("unsupported fallback provider")
    if fallback_provider != "disabled":
        fallback_endpoint = os.environ.get("FALLBACK_ENDPOINT", "").strip() or str(options.get("fallback_endpoint", "")).strip()
        fallback_key = os.environ.get("FALLBACK_API_KEY") or str(options.get("fallback_api_key", ""))
        route_id = "configured-fallback"
        if fallback_provider == "openrouter":
            fallback_endpoint = fallback_endpoint or DEFAULT_ENDPOINT
            fallback_model = os.environ.get("FALLBACK_MODEL", "").strip() or str(options.get("fallback_model", "")).strip()
            if not fallback_model:
                raise ValueError("fallback model is required for OpenRouter")
            adapter = OpenRouterFallbackAdapter(fallback_endpoint, model=fallback_model, api_key=fallback_key)
            hosted = True
        else:
            if not fallback_endpoint:
                raise ValueError("fallback endpoint is required")
            hosted = HttpJevClient(fallback_endpoint).hosted
            if hosted and urlsplit(fallback_endpoint).scheme != "https":
                raise ValueError("hosted fallback endpoint must use HTTPS")
            adapter = HttpRouteAdapter({route_id: fallback_endpoint}, api_keys={route_id: fallback_key})
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
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip() or str(options.get("jev_endpoint", "")).strip()
    api_key = os.environ.get("JEV_API_KEY") or str(options.get("jev_api_key", ""))
    parsed = urlsplit(endpoint)
    if parsed.hostname == "openrouter.ai" and parsed.scheme != "https":
        raise ValueError("OpenRouter endpoint must use HTTPS")
    if parsed.hostname == "openrouter.ai" and parsed.path.rstrip("/") == "/api/alpha/decisions":
        model = os.environ.get("JEV_MODEL", "").strip() or str(options.get("jev_model", "typesafe/jev-1.13")).strip()
        jev = OpenRouterDecisionsClient(endpoint, api_key=api_key, model=model)
    else:
        jev = HttpJevClient(endpoint, api_key=api_key) if endpoint else client_from_environment()
    privacy = PrivacyMode(str(options.get("privacy_mode") or os.environ.get("PRIVACY_MODE") or "local_only"))
    return Gateway(
        store=ProfileStore(data_dir),
        jev=jev,
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
        config=GatewayConfig(privacy_mode=privacy),
    )


def _load_options(data_dir: str) -> dict[str, Any]:
    path = os.path.join(data_dir, "options.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _load_supervisor_options()
    return value if isinstance(value, dict) else _load_supervisor_options()


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
    os.setgroups([])
    os.setgid(65532)
    os.setuid(65532)


def _retry_supervisor_discovery(port: int, gateway_token: str) -> None:
    """Keep startup-ordering races from permanently hiding the integration."""

    delay = threading.Event()
    while True:
        delay.wait(30)
        if register_supervisor_discovery(port=port, gateway_token=gateway_token):
            return


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

    return {
        "gateway_mode": str(options.get("gateway_mode") or "adapter_only"),
        "ingress_only": bool(ingress_only),
        "privacy_mode": str(options.get("privacy_mode") or "local_only"),
        "profile_refresh_minutes": int(options.get("profile_refresh_minutes") or 15),
        "auth_configured": bool(getattr(gateway, "gateway_token", "")),
        "fallback_provider": str(options.get("fallback_provider") or "disabled"),
        "fallback_configured": bool(getattr(getattr(gateway, "routes", None), "routes", ())),
    }


class GatewayHandler(BaseHTTPRequestHandler):
    gateway: Gateway
    ingress_only: bool = True
    app_status: dict[str, Any] = {}

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
        else:
            self._write(404, {"error": {"code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        trace = uuid.uuid4().hex[:12]
        started = time.monotonic()
        if not self._authorized():
            _LOG.warning("request trace=%s event=auth_denied path=%s", trace, _log_field(self.path.split("?", 1)[0]))
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
            elif path == "/v1/assist/process":
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
        except ValueError:
            _LOG.warning("request trace=%s event=invalid_request path=%s", trace, _log_field(self.path.split("?", 1)[0]))
            self._write(400, {"error": {"code": "invalid_request", "message": "request was invalid"}})
        except Exception as exc:
            _LOG.error("request trace=%s event=internal_error path=%s error_type=%s", trace, _log_field(self.path.split("?", 1)[0]), type(exc).__name__)
            self._write(500, {"error": {"code": "internal_error", "message": "request failed"}})

    def log_message(self, format: str, *args: Any) -> None:
        # The event logger records bounded outcomes without headers, bodies, or query strings.
        return

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise ValueError("request body length is invalid") from None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("request body is empty or oversized")
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
        self.wfile.write(raw)

    def _write_html(self, raw: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


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
    options = _load_options(args.data_dir)
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
