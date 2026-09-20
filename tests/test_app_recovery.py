from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from ha_switchboard.server import build_gateway
from custom_components.ha_switchboard import async_migrate_entry, async_unload_entry
from custom_components.ha_switchboard.const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL


ROOT = Path(__file__).parents[1]


def test_empty_options_keep_app_healthy_but_degraded_without_provider(tmp_path) -> None:
    gateway = build_gateway(str(tmp_path))

    assert gateway.health()["status"] == "ok"
    assert gateway.provider_status()["configured_count"] == 0
    assert gateway.ready()["status"] == "degraded"
    assert "provider_not_configured" in gateway.ready()["degraded_reasons"]


def test_runtime_hardening_keeps_image_code_immutable_and_data_scoped() -> None:
    dockerfile = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")
    apparmor = (ROOT / "app" / "apparmor.txt").read_text(encoding="utf-8")
    entrypoint = (ROOT / "app" / "run.sh").read_text(encoding="utf-8")

    assert "COPY --chown=65532:65532 ha_switchboard /app/ha_switchboard" in dockerfile
    assert "find /app -type f -exec chmod 0444 {} +" in dockerfile
    assert "USER 0:0" in dockerfile
    assert "/run.sh rix," in apparmor
    assert "/usr/local/bin/python3 rix," in apparmor
    assert "/usr/local/lib/** mr," in apparmor
    assert "/app/** r," in apparmor
    assert "/data/** rwk," in apparmor
    assert "exec /usr/local/bin/python3 -m ha_switchboard.server" in entrypoint
    assert "umask 077" in entrypoint


def test_core_migration_canonical_field_wins_during_token_rotation() -> None:
    async def run() -> None:
        updates = []
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=lambda entry, **kwargs: (
                    updates.append(kwargs), setattr(entry, "data", kwargs["data"])
                )
            )
        )
        entry = SimpleNamespace(
            data={
                "url": "http://legacy.invalid:8099",
                "token": "legacy-value",
                CONF_GATEWAY_URL: "http://current.invalid:8099",
                CONF_GATEWAY_TOKEN: "current-value",
            },
            version=0,
        )

        assert await async_migrate_entry(hass, entry)
        assert entry.data == {
            CONF_GATEWAY_URL: "http://current.invalid:8099",
            CONF_GATEWAY_TOKEN: "current-value",
        }
        assert updates and updates[0]["version"] == 1

    asyncio.run(run())


def test_core_unload_drops_previous_token_bearing_runtime() -> None:
    async def run() -> None:
        class Coordinator:
            async def async_shutdown(self):
                self.stopped = True

        class ConfigEntries:
            async def async_unload_platforms(self, _entry, _platforms):
                return True

        coordinator = Coordinator()
        entry = SimpleNamespace(entry_id="entry", runtime_data=SimpleNamespace(coordinator=coordinator))
        hass = SimpleNamespace(config_entries=ConfigEntries(), data={"ha_switchboard": {"entry": entry.runtime_data}})

        assert await async_unload_entry(hass, entry)
        assert entry.runtime_data is None
        assert hass.data["ha_switchboard"] == {}
        assert coordinator.stopped is True

    asyncio.run(run())
