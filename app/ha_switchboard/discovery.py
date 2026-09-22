"""Best-effort registration with the Home Assistant Supervisor discovery API."""

from __future__ import annotations

import json
import os
import re
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DISCOVERY_SERVICE = "ha_switchboard"
DEFAULT_SUPERVISOR_URL = "http://supervisor"
DEFAULT_PORT = 8099
DEFAULT_TIMEOUT = 1.0
DEFAULT_RETRIES = 3


def normalize_app_hostname(hostname: str) -> str:
    """Return a runtime hostname usable as a Home Assistant App DNS name.

    Supervisor's app network names may contain underscores, while the DNS
    alias exposed to Home Assistant uses hyphens. Preserve label boundaries,
    normalize case, and discard characters that cannot be part of a DNS name.
    """

    labels: list[str] = []
    for raw_label in hostname.strip().rstrip(".").split("."):
        label = raw_label.lower().replace("_", "-")
        label = re.sub(r"[^a-z0-9-]", "-", label)
        label = re.sub(r"-{2,}", "-", label).strip("-")
        if label:
            labels.append(label)
    normalized = ".".join(labels)
    if not normalized:
        raise ValueError("runtime hostname is empty")
    return normalized


def runtime_app_hostname() -> str:
    """Get and normalize the hostname assigned to this running App."""

    return normalize_app_hostname(os.environ.get("HOSTNAME", "") or socket.gethostname())


def _response_body(response: Any) -> None:
    """Consume an HTTP response without exposing its body in logs."""

    response.read()


def _supervisor_app_hostname(
    *,
    base_url: str,
    token: str,
    opener: Callable[..., Any],
    timeout: float,
) -> str | None:
    """Read the Supervisor-assigned DNS hostname for this running App.

    Docker's default container hostname may be an opaque container ID. The
    Supervisor app-info endpoint exposes the network hostname that Core can
    actually resolve. The App requests Supervisor API access only because the
    discovery POST also requires the scoped Supervisor token.
    """

    request = Request(
        f"{base_url}/addons/self/info",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read(64_000))
    except (HTTPError, OSError, TimeoutError, URLError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    hostname = data.get("hostname") if isinstance(data, dict) else None
    return hostname if isinstance(hostname, str) and hostname.strip() else None


def register_supervisor_discovery(
    *,
    port: int = DEFAULT_PORT,
    gateway_token: str = "",
    supervisor_token: str | None = None,
    supervisor_url: str | None = None,
    hostname: str | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Publish the gateway endpoint to Supervisor.

    Discovery is optional. Without ``SUPERVISOR_TOKEN`` this is a no-op, so
    the standalone image does not need a Supervisor-compatible service. The
    Supervisor API deduplicates messages by the calling app and service, so a
    repeated POST is safe and also updates a changed port or gateway token.
    """

    token_source = supervisor_token if supervisor_token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
    token = token_source.strip()
    if not token:
        return False

    if not 1 <= int(port) <= 65535:
        return False

    base_url = (
        supervisor_url or os.environ.get("SUPERVISOR") or DEFAULT_SUPERVISOR_URL
    ).rstrip("/")
    request_opener = opener or urlopen
    discovered_hostname = hostname or _supervisor_app_hostname(
        base_url=base_url,
        token=token,
        opener=request_opener,
        timeout=timeout,
    )
    try:
        app_hostname = normalize_app_hostname(discovered_hostname or runtime_app_hostname())
    except ValueError:
        return False

    payload = {
        "service": DISCOVERY_SERVICE,
        "config": {
            "host": app_hostname,
            "port": int(port),
            "token": gateway_token,
        },
    }
    request = Request(
        f"{base_url}/discovery",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(max(1, retries)):
        try:
            with request_opener(request, timeout=timeout) as response:
                _response_body(response)
            return True
        except (HTTPError, OSError, TimeoutError, URLError):
            if attempt + 1 >= max(1, retries):
                return False
            sleeper(0.1 * (attempt + 1))

    return False
