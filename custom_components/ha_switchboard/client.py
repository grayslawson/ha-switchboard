"""Credential-minimizing client from Home Assistant Core to the gateway."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class GatewayClientError(RuntimeError):
    pass


@dataclass(slots=True)
class GatewayClient:
    base_url: str
    gateway_token: str = ""
    timeout: float = 5.0

    async def health(self) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, "GET", "/healthz", None)

    async def status(self) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, "GET", "/v1/profile/status", None)

    async def reconcile(self, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, "POST", "/v1/profile/reconcile", {"snapshot": snapshot})

    async def process(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, "POST", "/v1/assist/process", payload)

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=max(0.2, min(self.timeout, 15))) as response:
                value = json.loads(response.read(128_000))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GatewayClientError("gateway unavailable") from exc
        if not isinstance(value, dict):
            raise GatewayClientError("gateway returned an invalid object")
        if "error" in value:
            raise GatewayClientError("gateway rejected the request")
        return value
