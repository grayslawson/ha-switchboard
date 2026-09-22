"""Minimize data crossing the gateway/provider boundary."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any
from ipaddress import ip_address
from urllib.parse import urlsplit


class SensitiveDataError(ValueError):
    """Raised when a credential or private Home Assistant reference crosses a boundary."""


SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "api_key",
        "apikey",
        "bearer",
        "cookie",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)

RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})
PRIVATE_STATE_KEYS = frozenset(
    {
        "camera",
        "latitude",
        "longitude",
        "location",
        "occupancy",
        "person",
        "presence",
        "alarm_code",
        "pin",
        "user_id",
    }
)


def _normalized_field_name(key: str) -> str:
    """Normalize spelling variants before applying boundary field policy."""

    return re.sub(r"[^a-z0-9]", "", key.casefold())


_SENSITIVE_FIELD_NAMES = frozenset(
    _normalized_field_name(item)
    for item in SENSITIVE_KEYS
    | {
        "accessKey",
        "auth",
        "authHeader",
        "authorizationHeader",
        "apiKey",
        "api-key",
        "api key",
        "bearerToken",
        "clientSecret",
        "client-secret",
        "credentialId",
        "credentialValue",
        "passwordHash",
        "privateKey",
        "refreshToken",
        "secretKey",
        "secretValue",
        "sessionToken",
        "tokenValue",
        "x-api-key",
        "x_api_key",
    }
)
_REFERENCE_FIELD_NAMES = frozenset(
    _normalized_field_name(item)
    for item in RAW_REFERENCE_KEYS
    | {"entityRef", "deviceRef", "areaRef", "uniqueId", "configEntryId"}
)
_CREDENTIAL_KEY_QUALIFIERS = frozenset(
    {
        "access",
        "api",
        "auth",
        "client",
        "credential",
        "encryption",
        "fallback",
        "private",
        "provider",
        "secret",
        "session",
        "signing",
        "x",
    }
)
_TRUSTED_LOCAL_SERVICE_HOSTS = frozenset({"localhost", "supervisor", "local-reasoner"})


def opaque_id(namespace: str, value: str, *, length: int = 20) -> str:
    """Return a stable non-reversible identifier for an adapter-local value."""

    if not namespace or not value:
        raise ValueError("namespace and value are required")
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8")).hexdigest()
    return f"{namespace[:16]}-{digest[:length]}"


def _key_is_sensitive(key: str) -> bool:
    normalized = _normalized_field_name(key)
    # Split separators and camel-case before considering a trailing ``key``;
    # this rejects fallback_api_key/secretKey/x-api-key without classifying
    # ordinary words such as ``monkey`` as credentials.
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    words = [part for part in re.split(r"[^a-zA-Z0-9]+", words.casefold()) if part]
    key_suffix = len(words) > 1 and words[-1] == "key" and words[-2] in _CREDENTIAL_KEY_QUALIFIERS
    return (
        normalized in _SENSITIVE_FIELD_NAMES
        or normalized.endswith("token")
        or normalized.endswith(("apikey", "secretkey", "privatekey"))
        or key_suffix
    )


def sanitize_for_gateway(value: Any, *, reject_references: bool = True) -> Any:
    """Copy JSON-like data while rejecting credentials and raw HA references.

    The function intentionally fails instead of silently masking a credential.
    Silent masking can make an integration appear safe while still sending
    malformed or unexpectedly private context to a provider.
    """

    def visit(item: Any, key: str | None = None) -> Any:
        if key is not None and _key_is_sensitive(key):
            raise SensitiveDataError(f"sensitive field {key!r} is not allowed")
        if reject_references and key is not None and _normalized_field_name(key) in _REFERENCE_FIELD_NAMES:
            raise SensitiveDataError(f"raw Home Assistant reference {key!r} is not allowed")
        if isinstance(item, Mapping):
            if len(item) > 128:
                raise SensitiveDataError("object exceeds bounded field count")
            return {str(k): visit(v, str(k)) for k, v in item.items()}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            # Complete capability profiles can contain far more than 128
            # entries. Request context remains on the smaller generic bound.
            limit = 2_000 if key in {"entities", "exposure", "capabilities"} else 128
            if len(item) > limit:
                raise SensitiveDataError("list exceeds bounded item count")
            return [visit(v, key) for v in item]
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and len(item) > 4_000:
                raise SensitiveDataError("text value exceeds bound")
            return item
        raise SensitiveDataError(f"unsupported value type {type(item).__name__}")

    return visit(value)


def sanitize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Remove privacy-sensitive state while preserving bounded useful facts."""

    if not isinstance(state, Mapping):
        raise SensitiveDataError("state must be an object")
    filtered = {key: value for key, value in state.items() if key.lower() not in PRIVATE_STATE_KEYS}
    return sanitize_for_gateway(filtered)


def sanitized_json(value: Any) -> str:
    """Serialize a validated payload deterministically for hashing or transport."""

    return json.dumps(sanitize_for_gateway(value), sort_keys=True, separators=(",", ":"))


def assert_no_secrets(value: Any) -> None:
    """Recursively verify that a value contains no credential-like field names."""

    sanitize_for_gateway(value, reject_references=False)


def endpoint_is_hosted(endpoint: str) -> bool:
    """Classify an endpoint conservatively; private/local destinations remain usable over HTTP."""

    host = (urlsplit(endpoint).hostname or "").lower()
    # Bare service names are not generally trusted: DNS search domains can
    # resolve an attacker-controlled-looking name outside the container.
    # Keep only service names used by this App's supported local topology.
    if host in _TRUSTED_LOCAL_SERVICE_HOSTS or host.endswith(".local"):
        return False
    try:
        return not ip_address(host).is_private
    except ValueError:
        return True


def require_secure_provider_endpoint(endpoint: str, *, has_credentials: bool, has_context: bool) -> None:
    """Reject remote HTTP when provider credentials or private context would cross it."""

    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("provider endpoint must be an absolute HTTP(S) URL")
    if endpoint_is_hosted(endpoint) and parsed.scheme.lower() != "https" and (has_credentials or has_context):
        raise ValueError("hosted provider endpoints carrying credentials or context must use HTTPS")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def open_provider_url(request: urllib.request.Request, *, timeout: float) -> Any:
    """Do not follow provider redirects because payload context is sensitive."""

    # Keep the established urllib.urlopen monkeypatch seam available to tests;
    # the real stdlib function takes the hardened no-redirect path.
    urlopen = urllib.request.urlopen
    if getattr(urlopen, "__module__", "urllib.request") == "urllib.request":
        return urllib.request.build_opener(_NoRedirectHandler()).open(request, timeout=timeout)
    return urlopen(request, timeout=timeout)
