from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tools" / "app-image-smoke.sh"


def test_local_app_smoke_harness_is_checked_in_and_scoped() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert HARNESS.stat().st_mode & 0o111
    assert "--platform" in text
    assert "HA_SWITCHBOARD_INGRESS_ONLY=false" in text
    assert "healthz" in text and "readyz" in text
    assert "/data/profile.json" in text
    assert "app-smoke-profile.json" in text
    assert "GATEWAY_TOKEN" in text
    assert "Authorization: Bearer" in text
    assert "restart" in text
    assert ".forgejo/workflows" not in text


def test_app_smoke_proves_non_root_server_on_supervisor_like_mount() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert "{{.Config.User}}" in text
    assert "65532:65532" in text
    assert "chmod 755" in text
    assert "/proc/1/status" in text
    assert "exec --user 65532:65532" in text


def test_app_smoke_accepts_provider_degraded_readiness_but_requires_active_profile() -> None:
    text = HARNESS.read_text(encoding="utf-8")

    assert 'wait_for_http /readyz 503' in text
    assert "expected provider-degraded state" in text
    assert 'status["status"] == "active"' in text
    assert 'status["capability_count"] > 0' in text
    assert 'payload.get("profile", payload)' in text


def test_smoke_harness_cleans_rootless_volume_and_fails_if_it_cannot() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert 'podman unshare rm -r -- "$TMP_DIR"' in text
    assert 'if [[ -e "$TMP_DIR" ]]' in text
    assert "result=1" in text
