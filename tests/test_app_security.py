from __future__ import annotations

from pathlib import Path

import json


ROOT = Path(__file__).parents[1]


def test_apparmor_does_not_make_application_tree_executable() -> None:
    profile = (ROOT / "app" / "apparmor.txt").read_text(encoding="utf-8")

    assert "/app/** r," in profile
    assert "/app/** rix," not in profile
    assert "deny /root/** rwklx" in profile
    assert "deny /config/** rwklx" in profile


def test_image_entrypoint_is_explicitly_readable_and_executable() -> None:
    dockerfile = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")
    profile = (ROOT / "app" / "apparmor.txt").read_text(encoding="utf-8")

    assert "COPY --chown=65532:65532 run.sh /run.sh" in dockerfile
    assert "RUN chmod 0555 /run.sh" in dockerfile
    assert "/run.sh rix," in profile
    assert "/usr/local/bin/python3 rix," in profile


def test_entrypoint_rejects_invalid_listener_ports_before_startup() -> None:
    entrypoint = (ROOT / "app" / "run.sh").read_text(encoding="utf-8")

    assert 'PORT="${JEV_PORT:-8099}"' in entrypoint
    assert "port must be a decimal value from 1 to 65535" in entrypoint
    assert '"$PORT" -lt 1' not in entrypoint
    assert "6553[0-5]" in entrypoint
    assert "[1-5][0-9][0-9][0-9][0-9]" in entrypoint
    assert '--port "$PORT"' in entrypoint
    assert '--port "${JEV_PORT:-8099}"' not in entrypoint


def test_e2e_token_is_only_used_for_local_contract_checks() -> None:
    harness = (ROOT / "tools" / "app-image-e2e.sh").read_text(encoding="utf-8")

    assert 'TOKEN="local-e2e-gateway-token"' in harness
    assert "env -i PATH=" in harness
    assert "JEV_API_KEY" not in harness
    assert "SUPERVISOR_TOKEN" not in harness


def test_entrypoint_preserves_root_only_supervisor_options_and_repairs_app_state() -> None:
    source = (ROOT / "app" / "ha_switchboard" / "server.py").read_text(encoding="utf-8")
    assert "PERSISTED_STATE_FILE_NAMES" in source
    assert "Supervisor's options.json contains credentials" in source
    assert "stat.S_ISLNK" in source


def test_root_transition_repairs_only_app_owned_state(monkeypatch, tmp_path) -> None:
    from ha_switchboard import server

    (tmp_path / "options.json").write_text(json.dumps({"gateway_token": "secret"}), encoding="utf-8")
    (tmp_path / "profile.json").write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(server.os, "geteuid", lambda: 0)
    monkeypatch.setattr(server.os, "chown", lambda path, uid, gid: calls.append((str(path), uid, gid)))
    monkeypatch.setattr(server.os, "setgroups", lambda groups: None)
    monkeypatch.setattr(server.os, "setgid", lambda gid: None)
    monkeypatch.setattr(server.os, "setuid", lambda uid: None)

    server._prepare_data_dir_and_drop_privileges(str(tmp_path))

    owned = {Path(path).name for path, _uid, _gid in calls}
    assert "profile.json" in owned
    assert "options.json" not in owned
