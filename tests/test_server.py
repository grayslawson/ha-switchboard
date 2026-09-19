from __future__ import annotations

from types import SimpleNamespace

from ha_switchboard.server import GatewayHandler


def _handler(*, source: str, ingress_only: bool, token: str, supplied: str = ""):
    handler = object.__new__(GatewayHandler)
    handler.client_address = (source, 12345)
    handler.path = "/v1/profile/status"
    handler.headers = {"Authorization": supplied}
    handler.gateway = SimpleNamespace(gateway_token=token)
    handler.ingress_only = ingress_only
    writes: list[tuple[int, dict[str, str]]] = []
    handler._write = lambda status, payload: writes.append((status, payload))
    return handler, writes


def test_ingress_only_rejects_direct_call_before_token_authentication() -> None:
    handler, writes = _handler(
        source="10.0.0.20",
        ingress_only=True,
        token="gateway-secret",
        supplied="Bearer gateway-secret",
    )

    assert handler._authorized() is False
    assert writes == [(403, {"error": {"code": "ingress_source_forbidden"}})]


def test_direct_adapter_mode_requires_gateway_token() -> None:
    handler, writes = _handler(source="10.0.0.20", ingress_only=False, token="")

    assert handler._authorized() is False
    assert writes == [(401, {"error": {"code": "gateway_token_required"}})]


def test_direct_adapter_mode_accepts_matching_gateway_token() -> None:
    handler, writes = _handler(
        source="10.0.0.20",
        ingress_only=False,
        token="gateway-secret",
        supplied="Bearer gateway-secret",
    )

    assert handler._authorized() is True
    assert writes == []


def test_ingress_source_can_use_protected_endpoints_without_gateway_token() -> None:
    handler, writes = _handler(source="172.30.32.2", ingress_only=True, token="")

    assert handler._authorized() is True
    assert writes == []
