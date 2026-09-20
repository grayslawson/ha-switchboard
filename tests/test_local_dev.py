from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "local-dev.sh"


def run_bash(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", *args], cwd=ROOT, env=merged, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def test_local_option_loader_accepts_jev_and_every_fallback_option_without_eval(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    options = tmp_path / ".env.local"
    options.write_text(
        "\n".join(
            [
                "HA_SWITCHBOARD_JEV_ENDPOINT=https://jev.example/decide",
                "HA_SWITCHBOARD_JEV_API_KEY=jev-key",
                "HA_SWITCHBOARD_FALLBACK_PROVIDER=typed_http",
                "HA_SWITCHBOARD_FALLBACK_ENDPOINT=http://127.0.0.1:8090/decide",
                "HA_SWITCHBOARD_FALLBACK_MODEL=local-model",
                "HA_SWITCHBOARD_FALLBACK_API_KEY=fallback-key",
                "HA_SWITCHBOARD_GATEWAY_TOKEN=gateway-token",
                "HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES=30",
                "HA_SWITCHBOARD_PRIVACY_MODE=hosted_allowed",
                f"HA_SWITCHBOARD_FALLBACK_MODEL=$(touch {marker})",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # The final duplicate is deliberately a literal command substitution. It
    # must be loaded as data, and the explicitly exported value must win.
    result = run_bash(
        "-c",
        f"source {SCRIPT!s}; LOCAL_OPTIONS_FILE={options!s}; "
        "export HA_SWITCHBOARD_FALLBACK_MODEL=exported-model; "
        "load_local_test_options; "
        "[[ $HA_SWITCHBOARD_JEV_ENDPOINT == https://jev.example/decide ]] && "
        "[[ $HA_SWITCHBOARD_FALLBACK_PROVIDER == typed_http ]] && "
        "[[ $HA_SWITCHBOARD_FALLBACK_MODEL == exported-model ]] && "
        "[[ $HA_SWITCHBOARD_PRIVACY_MODE == hosted_allowed ]]",
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "jev-key" not in result.stdout + result.stderr
    assert "gateway-token" not in result.stdout + result.stderr


def test_local_option_loader_rejects_unknown_and_unbalanced_values(tmp_path: Path) -> None:
    options = tmp_path / ".env.local"
    options.write_text("HA_SWITCHBOARD_NOT_ALLOWED=value\n", encoding="utf-8")
    unknown = run_bash("-c", f"source {SCRIPT!s}; LOCAL_OPTIONS_FILE={options!s}; load_local_test_options")
    assert unknown.returncode == 2
    assert "value" not in unknown.stdout + unknown.stderr

    options.write_text("HA_SWITCHBOARD_JEV_ENDPOINT=\"unclosed\n", encoding="utf-8")
    unbalanced = run_bash("-c", f"source {SCRIPT!s}; LOCAL_OPTIONS_FILE={options!s}; load_local_test_options")
    assert unbalanced.returncode == 2


def test_wait_budget_is_positive_and_failure_loops_are_bounded() -> None:
    result = run_bash("-c", f"source {SCRIPT!s}; WAIT_SECONDS=0; validate_wait_seconds")
    assert result.returncode == 2
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--max-time 5" in text
    assert "(( SECONDS < deadline )) && sleep 2" in text
    assert "did not become healthy within ${WAIT_SECONDS}s" in text


def test_normal_commands_refuse_fresh_environment_and_reset_is_explicit(tmp_path: Path) -> None:
    isolated_env = {"HA_SWITCHBOARD_STAGE_DIR": str(tmp_path / "missing-stage")}
    for command in ("start-ha", "wait", "store", "install", "start", "e2e", "sync-integration"):
        result = run_bash(str(SCRIPT), command, env=isolated_env)
        assert result.returncode != 0
        assert "run tools/local-dev.sh up first" in result.stderr

    for command in ("down", "clean"):
        result = run_bash(str(SCRIPT), command, env=isolated_env)
        assert result.returncode == 2
        assert "explicit 'reset' command" in result.stderr

    result = run_bash(str(SCRIPT), "reset", env=isolated_env)
    assert result.returncode != 0
    assert "destructive local reset" in result.stderr


def test_volume_preservation_and_snapshot_contract_are_visible() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--volumes-from" in text
    assert "tar -tzf \"$target\"" in text
    assert "HA_SWITCHBOARD_RESET_CONFIRM=RESET_LOCAL_HA_SWITCHBOARD" in text
    assert "ha apps rebuild --force" in text
    assert "docker volume rm" not in text


def test_normal_lifecycle_paths_never_reset_or_remove_the_volume() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    case_body = text.split('case "${1:-help}" in', 1)[1]

    for command in ("start-ha", "wait", "store", "install", "start", "e2e", "sync-integration"):
        branch = case_body.split(f"  {command})", 1)[1].split("\n    ;;", 1)[0]
        assert "reset_local_harness" not in branch
        assert "remove_devcontainer" not in branch
        assert "docker volume rm" not in branch

    for command in ("down", "clean"):
        branch = case_body.split(f"  {command})", 1)[1].split("\n    ;;", 1)[0]
        assert "reset_local_harness" not in branch
        assert "docker volume rm" not in branch
        assert "never removes the local volume" in branch


def test_reset_guard_and_snapshot_are_checked_before_mutation(tmp_path: Path) -> None:
    snapshot = tmp_path / "verified.snapshot.tar.gz"
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "marker").write_text("disposable", encoding="utf-8")
    subprocess.run(
        ["tar", "-czf", str(snapshot), "-C", str(payload), "."],
        check=True,
    )

    script = f"""
source {SCRIPT!s}
HA_SWITCHBOARD_SNAPSHOT_FILE={snapshot!s}
require_existing_harness() {{ :; }}
run_in_container() {{ printf 'run_in_container\n'; }}
remove_devcontainer() {{ printf 'remove_devcontainer\n'; }}
rm() {{ printf 'rm %s\n' "$*"; }}
reset_local_harness
"""
    unguarded = run_bash("-c", script)
    assert unguarded.returncode != 0
    assert "Refusing destructive local reset" in unguarded.stderr
    assert "remove_devcontainer" not in unguarded.stdout
    assert "rm -rf" not in unguarded.stdout

    guarded = run_bash(
        "-c",
        "HA_SWITCHBOARD_ALLOW_DEV_RESET=1 "
        "HA_SWITCHBOARD_RESET_CONFIRM=RESET_LOCAL_HA_SWITCHBOARD "
        + script,
    )
    assert guarded.returncode == 0, guarded.stderr
    assert "remove_devcontainer" in guarded.stdout
    assert "rm -rf" in guarded.stdout


def test_rebuild_updates_the_existing_app_without_recreating_core() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    rebuild = text.split("  rebuild)\n", 1)[1].split("\n    ;;", 1)[0]

    assert "devcontainer_id" in rebuild
    assert "sync_stage" in rebuild
    assert "wait_for_supervisor" in rebuild
    assert "ha apps stop '$APP_SLUG'" in rebuild
    assert "ha apps rebuild --force '$APP_SLUG'" in rebuild
    assert "ha apps start '$APP_SLUG'" in rebuild
    assert "remove_devcontainer" not in rebuild
    assert "docker volume rm" not in rebuild
    assert "ha core restart" not in rebuild


def test_update_path_refreshes_store_and_preserves_existing_installation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    install = text.split("install_app() {\n", 1)[1].split("\n}\n\nhas_local_options_env", 1)[0]

    assert "ha store reload" in install
    assert "app_already_installed_error" in install
    assert "ha apps start '$APP_SLUG'" in install
    assert "ha core restart" not in install
    assert "docker volume rm" not in install
