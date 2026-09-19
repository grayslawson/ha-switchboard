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


def test_app_smoke_uses_declared_non_root_identity() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert "{{.Config.User}}" in text
    assert "65532:65532" in text
    assert "id -u" in text and "id -g" in text
