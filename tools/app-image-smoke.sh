#!/usr/bin/env bash
set -Eeuo pipefail

# Build and exercise the local App image without Home Assistant, Jev, or
# credentials. Supervisor supplies the source-address boundary in production;
# this harness explicitly disables that boundary so it can use localhost.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${CONTAINER_ENGINE:-}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
KEEP_IMAGE="${KEEP_IMAGE:-0}"
IMAGE="${IMAGE:-ha-switchboard-local-smoke:$$}"
CONTAINER="ha-switchboard-local-smoke-$$"
ENGINE_NAME=""
BUILD_TIMEOUT_SECONDS=300
ENGINE_TIMEOUT_SECONDS=30
CLEANUP_TIMEOUT_SECONDS=15
SMOKE_GATEWAY_TOKEN="local-smoke-gateway-token"
TIMEOUT_BIN="$(command -v timeout || true)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ha-switchboard-smoke.XXXXXX")"
DATA_DIR="$TMP_DIR/data"
mkdir "$DATA_DIR"

# Match Supervisor's root-owned, non-world-writable /data mount.
chmod 755 "$DATA_DIR"

run_bounded() {
  local duration=$1
  shift
  [[ -n "$TIMEOUT_BIN" ]] || {
    echo "GNU timeout is required to bound smoke-test operations" >&2
    return 127
  }
  "$TIMEOUT_BIN" --kill-after=5s "$duration" "$@"
}

engine_command() {
  local duration=$1
  shift
  run_bounded "$duration" "$ENGINE" "$@"
}

remove_container() {
  if [[ "$ENGINE_NAME" == "podman" ]]; then
    engine_command "$ENGINE_TIMEOUT_SECONDS" rm --force --time 0 "$1" >/dev/null 2>&1
  else
    engine_command "$ENGINE_TIMEOUT_SECONDS" rm --force "$1" >/dev/null 2>&1
  fi
}

cleanup() {
  local result=$?
  trap - EXIT
  set +e
  local cleanup_failed=0
  if [[ -n "${CONTAINER_STARTED:-}" && -n "${ENGINE:-}" ]]; then
    remove_container "$CONTAINER" || cleanup_failed=1
  fi
  if [[ "$KEEP_IMAGE" != 1 && -n "${ENGINE:-}" ]]; then
    engine_command "$CLEANUP_TIMEOUT_SECONDS" image rm "$IMAGE" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if [[ "$ENGINE_NAME" == podman ]]; then
    engine_command "$CLEANUP_TIMEOUT_SECONDS" unshare rm -r -- "$TMP_DIR" >/dev/null 2>&1 || cleanup_failed=1
  else
    run_bounded "$CLEANUP_TIMEOUT_SECONDS" rm -r -- "$TMP_DIR" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if [[ -e "$TMP_DIR" ]]; then
    echo "smoke-test data cleanup failed: $TMP_DIR" >&2
    cleanup_failed=1
  fi
  if (( cleanup_failed )); then
    echo "smoke-test cleanup failed; inspect container=${CONTAINER:-unknown} image=${IMAGE:-unknown}" >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT

if [[ -z "$ENGINE" ]]; then
  if command -v podman >/dev/null 2>&1; then
    ENGINE=podman
  elif command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  else
    echo "no supported container engine found; install Podman or Docker" >&2
    exit 2
  fi
fi
command -v "$ENGINE" >/dev/null 2>&1 || {
  echo "container engine not found: $ENGINE" >&2
  exit 2
}
ENGINE_NAME="$(basename -- "$ENGINE")"
case "$ENGINE_NAME" in
  docker|podman) ;;
  *) echo "unsupported container engine: $ENGINE (use docker or podman)" >&2; exit 2 ;;
esac
TIMEOUT_BIN="$(command -v timeout || true)"
[[ -n "$TIMEOUT_BIN" ]] || {
  echo "GNU timeout is required to bound image build and cleanup operations" >&2
  exit 2
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required for local endpoint checks" >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to prepare the sanitized fixture" >&2
  exit 2
}

echo "engine=$ENGINE platform=$TARGET_PLATFORM"
echo "building App image"
engine_command "$BUILD_TIMEOUT_SECONDS" build \
  --platform "$TARGET_PLATFORM" \
  --build-arg BUILD_VERSION="${BUILD_VERSION:-local-smoke}" \
  --build-arg BUILD_ARCH=amd64 \
  --tag "$IMAGE" \
  "$ROOT_DIR/app"

declared_user=$(engine_command "$ENGINE_TIMEOUT_SECONDS" image inspect --format '{{.Config.User}}' "$IMAGE")
[[ "$declared_user" == "0:0" ]] || {
  echo "unexpected declared image user: $declared_user" >&2
  exit 1
}

echo "starting image with a root-only data preparation step"
engine_command "$ENGINE_TIMEOUT_SECONDS" run --detach --name "$CONTAINER" \
  --publish 127.0.0.1::8099 \
  --volume "$DATA_DIR:/data:rw" \
  --env GATEWAY_TOKEN="$SMOKE_GATEWAY_TOKEN" \
  --env HA_SWITCHBOARD_INGRESS_ONLY=false \
  "$IMAGE" >/dev/null
CONTAINER_STARTED=1

port=$(engine_command "$ENGINE_TIMEOUT_SECONDS" port "$CONTAINER" 8099/tcp | sed -n 's/.*://p' | head -n 1)
[[ "$port" =~ ^[0-9]+$ && "$port" != 0 ]] || {
  echo "could not determine published port" >&2
  exit 1
}
base_url="http://127.0.0.1:$port"

wait_for_http() {
  local path=$1 expected=$2 response code
  response="$TMP_DIR/response.json"
  for _ in {1..30}; do
    code=$(curl -s --connect-timeout 1 --max-time 2 \
      -o "$response" -w '%{http_code}' "$base_url$path" || true)
    if [[ "$code" == "$expected" ]]; then
      return 0
    fi
    sleep 0.2
  done
  echo "$path did not return HTTP $expected (last status: ${code:-none})" >&2
  return 1
}

request_code() {
  local output=$1 method=$2 path=$3
  shift 3
  curl -sS --connect-timeout 2 --max-time 5 \
    -o "$output" -w '%{http_code}' -X "$method" "$@" "$base_url$path"
}

wait_for_http /healthz 200
echo "/healthz: HTTP 200"

# With no reconciled profile, readiness is expected to be a safe degraded 503.
wait_for_http /readyz 503
echo "/readyz before profile: HTTP 503 (expected degraded state)"

status_code=$(request_code "$TMP_DIR/unauthorized.json" GET /v1/profile/status)
[[ "$status_code" == 401 ]] || {
  echo "protected profile status returned HTTP $status_code without a token" >&2
  exit 1
}
echo "/v1/profile/status without token: HTTP 401"

fixture="$ROOT_DIR/tests/fixtures/app-smoke-profile.json"
python3 - "$fixture" "$TMP_DIR/reconcile-request.json" <<'PY'
import json
import sys

fixture, output = sys.argv[1:]
with open(fixture, encoding="utf-8") as handle:
    snapshot = json.load(handle)
with open(output, "w", encoding="utf-8") as handle:
    json.dump({"snapshot": snapshot}, handle)
PY
reconcile_code=$(request_code "$TMP_DIR/reconcile.json" POST /v1/profile/reconcile \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $SMOKE_GATEWAY_TOKEN" \
  --data-binary "@$TMP_DIR/reconcile-request.json")
[[ "$reconcile_code" == 200 ]] || {
  echo "profile reconciliation failed (HTTP $reconcile_code)" >&2
  sed -n '1,3p' "$TMP_DIR/reconcile.json" >&2
  exit 1
}
# This smoke image deliberately has no Jev credential/provider. A reconciled
# profile is still valid and must persist, while readiness remains degraded
# until a decision provider is configured.
wait_for_http /readyz 503
echo "/readyz after local fixture: HTTP 503 (expected provider-degraded state)"

status_code=$(request_code "$TMP_DIR/status.json" GET /v1/profile/status \
  -H "Authorization: Bearer $SMOKE_GATEWAY_TOKEN")
[[ "$status_code" == 200 ]] || {
  echo "authorized profile status returned HTTP $status_code" >&2
  exit 1
}
python3 - "$TMP_DIR/status.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    status = json.load(handle)
assert status["status"] == "active", status
assert status["profile_revision"], status
assert status["capability_count"] > 0, status
PY

runtime_uid=$(engine_command "$ENGINE_TIMEOUT_SECONDS" exec "$CONTAINER" awk '/^Uid:/ {print $2}' /proc/1/status)
runtime_gid=$(engine_command "$ENGINE_TIMEOUT_SECONDS" exec "$CONTAINER" awk '/^Gid:/ {print $2}' /proc/1/status)
[[ "$runtime_uid" == 65532 && "$runtime_gid" == 65532 ]] || {
  echo "runtime identity is $runtime_uid:$runtime_gid, expected 65532:65532" >&2
  exit 1
}

# Reconciliation must persist sanitized profile state and leave the mounted data
# directory writable to the serving process after it drops privileges.
engine_command "$ENGINE_TIMEOUT_SECONDS" exec --user 65532:65532 "$CONTAINER" python3 -c '
from pathlib import Path
import json

path = Path("/data/profile.json")
assert path.is_file(), "profile.json was not persisted"
text = path.read_text()
payload = json.loads(text)
profile = payload.get("profile", payload)
assert profile.get("status") == "active", profile.get("status")
assert "entity_id" not in text, "raw entity reference persisted"
probe = Path("/data/.smoke-write")
probe.write_text("ok")
probe.unlink()
'
echo "/data: profile persisted, sanitized, and writable"

remove_container "$CONTAINER"
CONTAINER="$CONTAINER-restarted"
engine_command "$ENGINE_TIMEOUT_SECONDS" run --detach --name "$CONTAINER" --publish 127.0.0.1::8099 --volume "$DATA_DIR:/data:rw" --env GATEWAY_TOKEN="$SMOKE_GATEWAY_TOKEN" --env HA_SWITCHBOARD_INGRESS_ONLY=false "$IMAGE" >/dev/null
port=$(engine_command "$ENGINE_TIMEOUT_SECONDS" port "$CONTAINER" 8099/tcp | sed -n 's/.*://p' | head -n 1)
[[ "$port" =~ ^[0-9]+$ && "$port" != 0 ]] || {
  echo "could not determine replacement container port" >&2
  exit 1
}
base_url="http://127.0.0.1:$port"
wait_for_http /healthz 200
wait_for_http /readyz 503
status_code=$(request_code "$TMP_DIR/restarted-status.json" GET /v1/profile/status \
  -H "Authorization: Bearer $SMOKE_GATEWAY_TOKEN")
[[ "$status_code" == 200 ]] || {
  echo "profile status after restart returned HTTP $status_code" >&2
  exit 1
}
python3 - "$TMP_DIR/restarted-status.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    status = json.load(handle)
assert status["status"] == "stale", status
assert status["profile_revision"], status
PY
engine_command "$ENGINE_TIMEOUT_SECONDS" exec "$CONTAINER" test -s /data/profile.json
echo "restart/recreate: persisted profile restored as stale and writes remain fail-closed"
echo "local App image smoke passed"
