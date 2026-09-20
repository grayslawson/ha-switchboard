"""Supervisor discovery and explicit manual setup for the Core integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .client import GatewayClient, GatewayClientError
from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DOMAIN
from .opaque import opaque_id

CONF_CONFIRM = "confirm"


class DiscoveryValidationError(ValueError):
    """Supervisor discovery data is incomplete or unsafe to use."""


@dataclass(frozen=True, slots=True)
class GatewayEndpoint:
    url: str
    unique_id: str
    token: str = ""
    title: str = "HA Switchboard"

    def as_data(self) -> dict[str, str]:
        return {CONF_GATEWAY_URL: self.url, CONF_GATEWAY_TOKEN: self.token}


def _validate_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise DiscoveryValidationError("gateway URL is required")
    value = value.strip().rstrip("/")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise DiscoveryValidationError("gateway URL contains control characters")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise DiscoveryValidationError("gateway URL is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise DiscoveryValidationError("gateway URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DiscoveryValidationError("gateway URL may not contain credentials or query data")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DiscoveryValidationError("gateway port is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise DiscoveryValidationError("gateway port is invalid")
    if hostname and ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname or ""
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _endpoint_from_host(host: Any, port: Any, protocol: Any = "http") -> str:
    if not isinstance(host, str) or not host.strip() or any(char in host for char in "/?#"):
        raise DiscoveryValidationError("discovery host is invalid")
    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise DiscoveryValidationError("discovery port is required") from exc
    if not 1 <= port_number <= 65535:
        raise DiscoveryValidationError("discovery port is invalid")
    if protocol not in {"http", "https"}:
        raise DiscoveryValidationError("discovery protocol is invalid")
    host = host.strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return _validate_url(f"{protocol}://{host}:{port_number}")


def _discovery_mapping(payload: Any) -> Mapping[str, Any]:
    """Normalize HassioServiceInfo without flattening away its config boundary."""

    if isinstance(payload, Mapping):
        config = payload.get("config")
        if isinstance(config, Mapping):
            values = dict(config)
            for key in ("uuid", "slug", "name"):
                if payload.get(key) is not None:
                    values[f"_discovery_{key}"] = payload[key]
            return values
        return payload

    config = getattr(payload, "config", None)
    values = dict(config) if isinstance(config, Mapping) else {}
    for key in ("uuid", "slug", "name"):
        value = getattr(payload, key, None)
        if value is not None:
            values[f"_discovery_{key}"] = value
    return values


def validate_discovery_payload(payload: Mapping[str, Any] | Any) -> GatewayEndpoint:
    """Validate Supervisor's ``HassioServiceInfo(config=..., uuid=...)``."""

    values = _discovery_mapping(payload)
    if not isinstance(values, Mapping):
        raise DiscoveryValidationError("discovery payload must be an object")

    url = values.get(CONF_GATEWAY_URL) or values.get("url") or values.get("endpoint")
    if url:
        normalized_url = _validate_url(url)
    else:
        host = values.get("host") or values.get("hostname") or values.get("address")
        normalized_url = _endpoint_from_host(host, values.get("port"), values.get("protocol", "http"))

    identity = values.get("_discovery_uuid") or values.get("uuid")
    if identity is None:
        identity = values.get("instance_id") or values.get("installation_key") or values.get("slug")
    if identity is None:
        identity = opaque_id("gateway", normalized_url)
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 256:
        raise DiscoveryValidationError("discovery identity is invalid")

    token = values.get(CONF_GATEWAY_TOKEN, values.get("token", ""))
    if token is None:
        token = ""
    if not isinstance(token, str) or len(token) > 512 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in token):
        raise DiscoveryValidationError("discovery token is invalid")

    title = values.get("_discovery_name") or values.get("name") or "HA Switchboard"
    if not isinstance(title, str) or not title.strip() or len(title) > 128:
        title = "HA Switchboard"
    return GatewayEndpoint(normalized_url, identity.strip(), token, title.strip())


def validate_manual_input(user_input: Mapping[str, Any]) -> GatewayEndpoint:
    if not isinstance(user_input, Mapping):
        raise DiscoveryValidationError("setup input must be an object")
    url = _validate_url(user_input.get(CONF_GATEWAY_URL))
    token = user_input.get(CONF_GATEWAY_TOKEN, "")
    if not isinstance(token, str) or len(token) > 512 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in token):
        raise DiscoveryValidationError("gateway token is invalid")
    return GatewayEndpoint(url, opaque_id("gateway", url), token)


try:  # pragma: no cover - Home Assistant supplies these at runtime
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
        VERSION = 1

        async def async_step_hassio(self, discovery_info: HassioServiceInfo):
            try:
                endpoint = validate_discovery_payload(discovery_info)
            except DiscoveryValidationError:
                return self.async_abort(reason="invalid_discovery")
            await self.async_set_unique_id(endpoint.unique_id)
            self._abort_if_unique_id_configured(updates=endpoint.as_data(), reload_on_update=False)
            self._pending = endpoint
            self._pending_step = "hassio_confirm"
            return await self.async_step_hassio_confirm()

        async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None):
            endpoint = getattr(self, "_pending", None)
            if endpoint is None:
                return self.async_abort(reason="invalid_discovery")
            if user_input is None:
                return self.async_show_form(
                    step_id="hassio_confirm",
                    data_schema=vol.Schema({vol.Required(CONF_CONFIRM, default=True): bool}),
                    description_placeholders={"gateway_url": endpoint.url},
                )
            if not user_input.get(CONF_CONFIRM, False):
                return self.async_abort(reason="user_cancelled")
            return await self._async_validate_and_create(endpoint)

        async def async_step_user(self, user_input: dict[str, Any] | None = None):
            if user_input is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_GATEWAY_URL): str,
                            vol.Optional(CONF_GATEWAY_TOKEN, default=""): str,
                        }
                    ),
                )
            try:
                endpoint = validate_manual_input(user_input)
            except DiscoveryValidationError:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_GATEWAY_URL): str, vol.Optional(CONF_GATEWAY_TOKEN, default=""): str}
                    ),
                    errors={"base": "invalid_url"},
                )
            await self.async_set_unique_id(endpoint.unique_id)
            self._abort_if_unique_id_configured()
            self._pending = endpoint
            self._pending_step = "confirm"
            return await self.async_step_confirm()

        async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
            endpoint = getattr(self, "_pending", None)
            if endpoint is None:
                return self.async_abort(reason="invalid_url")
            if user_input is None:
                return self.async_show_form(
                    step_id="confirm",
                    data_schema=vol.Schema({vol.Required(CONF_CONFIRM, default=True): bool}),
                    description_placeholders={"gateway_url": endpoint.url},
                )
            if not user_input.get(CONF_CONFIRM, False):
                return self.async_abort(reason="user_cancelled")
            return await self._async_validate_and_create(endpoint)

        async def _async_validate_and_create(self, endpoint: GatewayEndpoint):
            try:
                client = GatewayClient.from_hass(self.hass, endpoint.url, endpoint.token)
                await client.health()
                # Health is intentionally public, but the actual Core API is
                # token-protected. Verify that boundary before creating an
                # entry which would otherwise fail during integration setup.
                await client.status()
            except GatewayClientError:
                return self.async_show_form(
                    step_id=getattr(self, "_pending_step", "confirm"),
                    data_schema=vol.Schema({vol.Required(CONF_CONFIRM, default=True): bool}),
                    errors={"base": "cannot_connect"},
                    description_placeholders={"gateway_url": endpoint.url},
                )
            return self.async_create_entry(title=endpoint.title, data=endpoint.as_data())

except ImportError:

    class ConfigFlow:  # type: ignore[no-redef]
        """Contract-test fallback used when Home Assistant is not installed."""

        VERSION = 1

        def __init__(self, user_input: dict[str, Any] | None = None) -> None:
            self.user_input = user_input
            self._pending: GatewayEndpoint | None = None

        async def async_step_user(self, user_input: dict[str, Any] | None = None):
            if user_input is None:
                return {"type": "form", "step_id": "user"}
            try:
                self._pending = validate_manual_input(user_input)
            except DiscoveryValidationError:
                return {"type": "form", "step_id": "user", "errors": {"base": "invalid_url"}}
            return {"type": "form", "step_id": "confirm"}

        async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
            if self._pending is None:
                return {"type": "abort", "reason": "invalid_url"}
            if not user_input or not user_input.get(CONF_CONFIRM, False):
                return {"type": "abort", "reason": "user_cancelled"}
            return {"type": "create_entry", "title": self._pending.title, "data": self._pending.as_data()}

        async def async_step_hassio(self, discovery_info: Mapping[str, Any] | None = None):
            try:
                self._pending = validate_discovery_payload(discovery_info or {})
            except DiscoveryValidationError:
                return {"type": "abort", "reason": "invalid_discovery"}
            return {"type": "form", "step_id": "hassio_confirm"}

        async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None):
            if not user_input or not user_input.get(CONF_CONFIRM, False) or self._pending is None:
                return {"type": "abort", "reason": "user_cancelled"}
            return {"type": "create_entry", "title": self._pending.title, "data": self._pending.as_data()}
