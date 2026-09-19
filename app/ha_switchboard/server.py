"""Small standard-library HTTP server for the App and standalone image."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .gateway import Gateway
from .handoff import HandoffBroker, StaticRouteAdapter
from .jev_client import HttpJevClient, client_from_environment
from .route_policy import RouteRegistry
from .store import ProfileStore


def build_gateway(data_dir: str) -> Gateway:
    options = _load_options(data_dir)
    route_json = os.environ.get("JEV_ROUTE_REGISTRY", "")
    routes = RouteRegistry.from_dict(json.loads(route_json)) if route_json else RouteRegistry()
    adapter = StaticRouteAdapter({})
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip() or str(options.get("jev_endpoint", "")).strip()
    api_key = os.environ.get("JEV_API_KEY") or str(options.get("jev_api_key", ""))
    jev = HttpJevClient(endpoint, api_key=api_key) if endpoint else client_from_environment()
    return Gateway(
        store=ProfileStore(data_dir),
        jev=jev,
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
    )


def _load_options(data_dir: str) -> dict[str, Any]:
    path = os.path.join(data_dir, "options.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class GatewayHandler(BaseHTTPRequestHandler):
    gateway: Gateway
    ingress_only: bool = True

    server_version = "ha-switchboard/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            return
        if self.path == "/healthz":
            self._write(200, self.gateway.health())
        elif self.path == "/readyz":
            body = self.gateway.ready()
            self._write(200 if body["status"] == "ready" else 503, body)
        elif self.path == "/v1/profile/status":
            self._write(200, self.gateway.profile_status())
        else:
            self._write(404, {"error": {"code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            return
        try:
            payload = self._read_json()
            if self.path == "/v1/profile/reconcile":
                snapshot = payload.get("snapshot")
                if not isinstance(snapshot, dict):
                    raise ValueError("snapshot is required")
                self._write(200, self.gateway.reconcile(snapshot))
            elif self.path == "/v1/profile/invalidate":
                self._write(200, self.gateway.invalidate(payload))
            elif self.path == "/v1/assist/process":
                self._write(200, self.gateway.process(payload).to_dict())
            else:
                self._write(404, {"error": {"code": "not_found"}})
        except ValueError as exc:
            self._write(400, {"error": {"code": "invalid_request", "message": str(exc)}})
        except Exception:
            self._write(500, {"error": {"code": "internal_error", "message": "request failed"}})

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs bounded and free of request bodies/credentials.
        print(f"gateway {self.command} {self.path} {args[1] if len(args) > 1 else ''}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 64_000:
            raise ValueError("request body is empty or oversized")
        raw = self.rfile.read(length)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _authorized(self) -> bool:
        if self.ingress_only and self.client_address[0] != "172.30.32.2":
            self._write(403, {"error": {"code": "ingress_source_forbidden"}})
            return False
        expected = getattr(self.gateway, "gateway_token", "")
        if not expected or self.path in {"/healthz", "/readyz"}:
            return True
        supplied = self.headers.get("Authorization", "")
        if supplied == f"Bearer {expected}":
            return True
        self._write(401, {"error": {"code": "unauthorized"}})
        return False

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="HA Switchboard gateway")
    parser.add_argument("--data-dir", default="/data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
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
        {"gateway": gateway, "ingress_only": ingress_only},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"ha-switchboard gateway listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
