"""Adapter protocol and read-only transport helpers.

The portable gateway never uses this module with a Home Assistant bearer token
in normal App mode. It documents the adapter-side split and is useful for the
standalone scanner/fixture path.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class HomeAssistantTransport(Protocol):
    def read(self, path: str) -> Any: ...

    def subscribe_events(self) -> Any: ...

    def execute(self, domain: str, operation: str, target: Mapping[str, Any], parameters: Mapping[str, Any]) -> Any: ...


@dataclass(slots=True)
class ReadOnlyRestClient:
    base_url: str
    token: str
    timeout: float = 5.0

    def read(self, path: str) -> Any:
        if not path.startswith("/"):
            raise ValueError("Home Assistant path must be absolute")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read(1_000_000))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("Home Assistant read failed") from exc

    def subscribe_events(self) -> Any:
        raise NotImplementedError("WebSocket event subscription belongs to the Core adapter")

    def execute(self, domain: str, operation: str, target: Mapping[str, Any], parameters: Mapping[str, Any]) -> Any:
        raise PermissionError("read-only scanner transport cannot execute Home Assistant actions")
