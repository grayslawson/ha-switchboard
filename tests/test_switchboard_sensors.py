"""Contract tests for the read-only Switchboard diagnostic sensors."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.ha_switchboard.sensor import _SwitchboardDiagnosticSensor


class _Client:
    def __init__(self, status=None, error=None):
        self.value = status or {}
        self.error = error

    async def status(self):
        if self.error:
            raise self.error
        return self.value


def test_sensors_expose_only_safe_gateway_status_values():
    client = _Client(
        {
            "status": "active",
            "stale": False,
            "capability_count": 23,
            "last_reconciled_at": "2026-09-20T00:00:00Z",
            "profile_revision": "secret-ish-revision",
            "gateway_url": "https://private.example",
            "gateway_token": "do-not-expose",
        }
    )

    ready = _SwitchboardDiagnosticSensor(client, "entry", "ready")
    capabilities = _SwitchboardDiagnosticSensor(client, "entry", "capabilities")
    last_scan = _SwitchboardDiagnosticSensor(client, "entry", "last_scan")
    asyncio.run(ready.async_update())
    asyncio.run(capabilities.async_update())
    asyncio.run(last_scan.async_update())

    assert ready._attr_unique_id == "entry_ready"
    assert ready._attr_native_value == "ready"
    assert capabilities._attr_native_value == 23
    assert last_scan._attr_native_value == "2026-09-20T00:00:00Z"
    assert set(ready._attr_extra_state_attributes) <= {
        "status", "stale", "capability_count", "last_reconciled_at"
    }
    assert "gateway_token" not in ready._attr_extra_state_attributes
    assert "gateway_url" not in ready._attr_extra_state_attributes
    assert "profile_revision" not in ready._attr_extra_state_attributes


def test_ready_is_false_when_profile_is_stale():
    sensor = _SwitchboardDiagnosticSensor(
        _Client({"status": "active", "stale": True, "capability_count": 2}), "entry", "ready"
    )
    asyncio.run(sensor.async_update())
    assert sensor._attr_available is True
    assert sensor._attr_native_value == "degraded"


def test_sensors_become_unavailable_when_gateway_status_fails():
    sensor = _SwitchboardDiagnosticSensor(_Client(error=RuntimeError("offline")), "entry", "ready")
    asyncio.run(sensor.async_update())
    assert sensor._attr_available is False
    assert sensor._attr_native_value is None
    assert sensor._attr_extra_state_attributes == {}


def test_last_scan_has_explicit_never_value_before_first_reconcile():
    sensor = _SwitchboardDiagnosticSensor(_Client({"status": "empty", "stale": True}), "entry", "last_scan")
    asyncio.run(sensor.async_update())
    assert sensor._attr_available is True
    assert sensor._attr_native_value == "Never"
