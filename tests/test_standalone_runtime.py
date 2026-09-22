from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_standalone_defaults_keep_gateway_on_loopback() -> None:
    compose = (ROOT / "standalone" / "compose.yaml").read_text(encoding="utf-8")

    assert '"127.0.0.1:${HA_SWITCHBOARD_PORT:-8099}:8099"' in compose
    assert 'HA_SWITCHBOARD_INGRESS_ONLY: "false"' in compose
    assert 'GATEWAY_TOKEN: "${GATEWAY_TOKEN:-}"' in compose


def test_standalone_root_filesystem_is_read_only_with_non_executable_tmp() -> None:
    compose = (ROOT / "standalone" / "compose.yaml").read_text(encoding="utf-8")

    assert "read_only: true" in compose
    assert "/tmp:rw,noexec,nosuid,nodev" in compose


def test_entrypoint_uses_fixed_interpreter_and_private_umask() -> None:
    run_sh = (ROOT / "app" / "run.sh").read_text(encoding="utf-8")

    assert "umask 077" in run_sh
    assert "exec /usr/local/bin/python3 -m ha_switchboard.server" in run_sh
    assert "exec python3 -m" not in run_sh


def test_entrypoint_constrains_root_owned_data_path() -> None:
    run_sh = (ROOT / "app" / "run.sh").read_text(encoding="utf-8")
    assert "data directory must remain under /data" in run_sh
    assert "parent traversal" in run_sh
