"""Async Home Assistant Core client for the Switchboard App gateway."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Mapping

try:  # Home Assistant supplies aiohttp; contract tests do not need it.
    from aiohttp import ClientError
except ImportError:  # pragma: no cover
    class ClientError(Exception):
        pass


class GatewayClientError(RuntimeError):
    """The gateway could not be reached or rejected the bounded request."""


@dataclass(slots=True)
class GatewayClient:
    base_url: str
    gateway_token: str = ""
    timeout: float = 5.0
    session: Any = None

    @classmethod
    def from_hass(
        cls,
        hass: Any,
        base_url: str,
        gateway_token: str = "",
        timeout: float = 5.0,
    ) -> "GatewayClient":
        """Use Home Assistant's shared async HTTP session."""

        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
        except ImportError as exc:  # pragma: no cover
            raise GatewayClientError("Home Assistant web session support is unavailable") from exc
        return cls(base_url, gateway_token, timeout, async_get_clientsession(hass))

    async def health(self) -> Mapping[str, Any]:
        return await self._request("GET", "/healthz", None)

    async def status(self) -> Mapping[str, Any]:
        return await self._request("GET", "/v1/profile/status", None)

    async def app_status(self) -> Mapping[str, Any]:
        """Read the authenticated, non-secret App options/status payload."""

        return await self._request("GET", "/v1/app/status", None)

    async def reconcile(self, snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._request("POST", "/v1/profile/reconcile", {"snapshot": snapshot})

    async def invalidate(self, event_type: str) -> Mapping[str, Any]:
        return await self._request("POST", "/v1/profile/invalidate", {"event_type": event_type})

    async def process(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._request("POST", "/v1/assist/process", payload)

    async def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if self.session is None:
            raise GatewayClientError("Home Assistant web session is not configured")
        url = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            request = self.session.request(
                method,
                url,
                data=body,
                headers=headers,
                timeout=max(0.2, min(self.timeout, 15)),
            )
            if hasattr(request, "__aenter__"):
                async with request as response:
                    return await self._read_response(response)
            response = await request if inspect.isawaitable(request) else request
            return await self._read_response(response)
        except (ClientError, OSError, TimeoutError, RuntimeError) as exc:
            raise GatewayClientError("gateway unavailable") from exc

    async def _read_response(self, response: Any) -> dict[str, Any]:
        if int(getattr(response, "status", 200)) >= 400:
            raise GatewayClientError("gateway rejected the request")
        try:
            parser = getattr(response, "json")
            try:
                parsed = parser(content_type=None)
            except TypeError:
                parsed = parser()
            value = await parsed if inspect.isawaitable(parsed) else parsed
        except (ValueError, TypeError, AttributeError) as exc:
            raise GatewayClientError("gateway returned invalid JSON") from exc
        if not isinstance(value, dict) or "error" in value:
            raise GatewayClientError("gateway returned an invalid object")
        return value
