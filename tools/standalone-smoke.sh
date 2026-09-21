#!/usr/bin/env bash
set -Eeuo pipefail

# Validate the rendered standalone Compose model without building, pulling,
# starting, or contacting a registry. This is deliberately credential-free.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/standalone/compose.yaml"
TIMEOUT_BIN="$(command -v timeout || true)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ha-switchboard-compose-smoke.XXXXXX")"
CONFIG_JSON="$TMP_DIR/config.json"
COMPOSE_TIMEOUT_SECONDS=30

cleanup() {
  local result=$?
  trap - EXIT
  set +e
  if [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" --kill-after=2s 5s rm -rf -- "$TMP_DIR" >/dev/null 2>&1
  else
    rm -rf -- "$TMP_DIR"
  fi
  exit "$result"
}
trap cleanup EXIT

[[ -n "$TIMEOUT_BIN" ]] || { echo "GNU timeout is required" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }

compose_cmd=()
if [[ -n "${COMPOSE_BIN:-}" ]]; then
  command -v "$COMPOSE_BIN" >/dev/null 2>&1 || {
    echo "COMPOSE_BIN not found: $COMPOSE_BIN" >&2
    exit 2
  }
  compose_cmd=("$COMPOSE_BIN")
elif command -v docker >/dev/null 2>&1 && "$TIMEOUT_BIN" --kill-after=2s 5s docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
elif command -v podman >/dev/null 2>&1 && "$TIMEOUT_BIN" --kill-after=2s 5s podman compose version >/dev/null 2>&1; then
  compose_cmd=(podman compose)
else
  echo "no supported Compose command found" >&2
  exit 2
fi

# env -i prevents workstation credentials and provider settings from entering
# interpolation. Keep all declared secret-bearing inputs explicitly empty.
env -i \
  PATH="$PATH" \
  HOME="$TMP_DIR/home" \
  COMPOSE_PROJECT_NAME=ha-switchboard-standalone-smoke \
  HA_SWITCHBOARD_PORT=18099 \
  HA_SWITCHBOARD_DATA="$TMP_DIR/data" \
  JEV_PROVIDER=disabled \
  JEV_ENDPOINT= \
  JEV_BASE_URL= \
  JEV_API_KEY= \
  JEV_MODEL=typesafe/jev-1.13 \
  PRIVACY_MODE=local_only \
  FALLBACK_PROVIDER=disabled \
  FALLBACK_BASE_URL= \
  FALLBACK_ENDPOINT= \
  FALLBACK_MODEL= \
  FALLBACK_API_KEY= \
  GATEWAY_TOKEN= \
  HA_SWITCHBOARD_INGRESS_ONLY=false \
  "$TIMEOUT_BIN" --kill-after=2s "$COMPOSE_TIMEOUT_SECONDS" \
  "${compose_cmd[@]}" -f "$COMPOSE_FILE" config --format json >"$CONFIG_JSON"

python3 - "$CONFIG_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    document = json.load(handle)

service = document.get("services", {}).get("ha-switchboard")
assert isinstance(service, dict), "ha-switchboard service is missing"

ports = service.get("ports", [])
assert any(
    port.get("host_ip") == "127.0.0.1"
    and int(port.get("target")) == 8099
    and int(port.get("published")) == 18099
    for port in ports
    if isinstance(port, dict)
), f"gateway is not loopback-published: {ports!r}"

assert service.get("read_only") is True, "root filesystem must be read-only"
tmpfs = service.get("tmpfs", [])
assert "/tmp:rw,noexec,nosuid,nodev" in tmpfs, f"unsafe /tmp mount: {tmpfs!r}"

volumes = service.get("volumes", [])
data_mounts = [mount for mount in volumes if mount.get("target") == "/data"]
assert len(data_mounts) == 1, f"expected one persistent /data bind: {volumes!r}"
data_mount = data_mounts[0]
assert data_mount.get("type") == "bind", f"/data is not a bind mount: {data_mount!r}"
assert data_mount.get("source"), "persistent /data source is empty"
assert data_mount.get("read_only") is not True, "/data must be writable for persistence"

healthcheck = service.get("healthcheck")
assert isinstance(healthcheck, dict), "healthcheck is missing"
health_test = healthcheck.get("test", [])
assert "healthz" in " ".join(map(str, health_test)), f"healthcheck misses /healthz: {health_test!r}"
for key in ("interval", "timeout", "retries"):
    assert healthcheck.get(key), f"healthcheck {key} is missing"

environment = service.get("environment", {})
assert environment.get("HA_SWITCHBOARD_INGRESS_ONLY") in (False, "false"), \
    "standalone mode must disable the Supervisor ingress boundary"
for name in ("JEV_API_KEY", "FALLBACK_API_KEY", "GATEWAY_TOKEN"):
    assert environment.get(name) in (None, ""), f"{name} must be empty in the smoke"
for name in ("JEV_ENDPOINT", "JEV_BASE_URL", "FALLBACK_BASE_URL", "FALLBACK_ENDPOINT"):
    assert environment.get(name) in (None, ""), f"{name} must be empty in the smoke"

print("standalone Compose model: loopback, filesystem, persistence, healthcheck, boundary, and secret-free wiring OK")
PY
