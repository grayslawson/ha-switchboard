#!/usr/bin/env bash
set -Eeuo pipefail

# Build and exercise the current App image on an isolated local network. This
# is deliberately independent of the published GHCR image and needs no
# provider credentials. The official Supervisor devcontainer remains the
# authoritative full App+Core test; this script proves the image boundary and
# the source-address/token contract quickly on the host.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${CONTAINER_ENGINE:-}"
ARCH="amd64"
VERSION="local-e2e"
APPARMOR_PROFILE=""
SUPERVISOR_HOOK=""
INTEGRATION_HOOK=""
KEEP="false"
TOKEN="local-e2e-gateway-token"

usage() {
  cat <<'EOF'
Usage: tools/app-image-e2e.sh [options]

Options:
  --engine ENGINE              docker or podman (default: detected)
  --arch amd64|arm64          target Docker architecture (default: amd64)
  --version VERSION            local build version (default: local-e2e)
  --apparmor-profile PROFILE   enforce a loaded host AppArmor profile
  --supervisor-hook COMMAND    optional discovery-hook command
  --integration-hook COMMAND   optional integration-hook command
  --keep                       keep the validation container, network, and data
EOF
}

while (($#)); do
  case "$1" in
    --engine) ENGINE="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --apparmor-profile) APPARMOR_PROFILE="$2"; shift 2 ;;
    --supervisor-hook) SUPERVISOR_HOOK="$2"; shift 2 ;;
    --integration-hook) INTEGRATION_HOOK="$2"; shift 2 ;;
    --keep) KEEP=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$ARCH" in
  amd64) HA_ARCH=amd64 ;;
  arm64) HA_ARCH=aarch64 ;;
  *) echo "unsupported Docker architecture: $ARCH" >&2; exit 2 ;;
esac

if [[ -z "$ENGINE" ]]; then
  if command -v podman >/dev/null 2>&1; then ENGINE=podman
  elif command -v docker >/dev/null 2>&1; then ENGINE=docker
  else echo "no docker or podman executable found" >&2; exit 127
  fi
fi
command -v "$ENGINE" >/dev/null 2>&1 || { echo "container engine not found: $ENGINE" >&2; exit 127; }
case "$(basename -- "$ENGINE")" in
  docker|podman) ;;
  *) echo "unsupported container engine: $ENGINE (use docker or podman)" >&2; exit 2 ;;
esac

IMAGE="localhost/ha-switchboard-local:${VERSION}-${ARCH}"
RUN_NAME="ha-switchboard-e2e-$$"
NETWORK="ha-switchboard-e2e-$$"
DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ha-switchboard-e2e.XXXXXX")"
chmod 0755 "$DATA_DIR"
NETWORK_CREATED=false
CONTAINER_CREATED=false

cleanup() {
  local result=$?
  if [[ "$KEEP" == true ]]; then
    echo "kept validation resources: container=$RUN_NAME network=$NETWORK data=$DATA_DIR"
    exit "$result"
  fi
  trap - EXIT
  set +e
  local cleanup_failed=0
  if [[ "$CONTAINER_CREATED" == true ]]; then
    "$ENGINE" rm --force "$RUN_NAME" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if [[ "$NETWORK_CREATED" == true ]]; then
    "$ENGINE" network rm "$NETWORK" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if [[ "$ENGINE" == podman ]]; then
    # Rootless Podman maps container UID 65532 to a subordinate host UID.
    "$ENGINE" unshare rm -r -- "$DATA_DIR" >/dev/null 2>&1 || cleanup_failed=1
  else
    # Docker leaves the bind mount owned by the dropped runtime UID.
    "$ENGINE" run --rm --user 0 \
      --mount "type=bind,src=${DATA_DIR},dst=/data" \
      --entrypoint chown "$IMAGE" "$(id -u):$(id -g)" /data >/dev/null 2>&1 || cleanup_failed=1
    rm -r -- "$DATA_DIR" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if [[ -e "$DATA_DIR" ]]; then
    echo "E2E cleanup failed; data remains at $DATA_DIR" >&2
    cleanup_failed=1
  fi
  if (( cleanup_failed )); then
    echo "E2E cleanup failed; inspect container=$RUN_NAME network=$NETWORK" >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT

echo "== build current source: $ROOT_DIR/app -> $IMAGE"
BUILD_PULL_ARGS=()
if [[ "$ENGINE" == podman ]]; then
  BUILD_PULL_ARGS=(--pull=missing)
fi
"$ENGINE" build "${BUILD_PULL_ARGS[@]}" --platform "linux/${ARCH}" \
  --tag "$IMAGE" \
  --label "ha-switchboard.source=local:${VERSION}" \
  --build-arg "BUILD_VERSION=${VERSION}" \
  --build-arg "BUILD_ARCH=${HA_ARCH}" \
  "$ROOT_DIR/app"

inspect_json="$($ENGINE image inspect "$IMAGE")"
readarray -t image_facts < <(python3 -c '
import json, sys
image = json.load(sys.stdin)[0]
config = image.get("Config", {})
labels = config.get("Labels") or {}
print(config.get("User", ""))
print(labels.get("io.hass.arch", ""))
print(labels.get("io.hass.version", ""))
print(labels.get("ha-switchboard.source", ""))
' <<<"$inspect_json")
[[ "${image_facts[0]}" == "0:0" ]] || { echo "image startup user mismatch" >&2; exit 1; }
[[ "${image_facts[1]}" == "$HA_ARCH" ]] || { echo "Home Assistant architecture mismatch" >&2; exit 1; }
[[ "${image_facts[2]}" == "$VERSION" ]] || { echo "image version mismatch" >&2; exit 1; }
[[ "${image_facts[3]}" == "local:${VERSION}" ]] || { echo "local source marker missing" >&2; exit 1; }

SECURITY_OPT=()
if [[ -n "$APPARMOR_PROFILE" ]]; then
  SECURITY_OPT=(--security-opt "apparmor=${APPARMOR_PROFILE}")
  echo "AppArmor enforcement: ${APPARMOR_PROFILE}"
else
  echo "AppArmor enforcement: not requested"
fi

"$ENGINE" network create --subnet 172.30.32.0/24 --gateway 172.30.32.1 "$NETWORK" >/dev/null
NETWORK_CREATED=true
"$ENGINE" run --detach --name "$RUN_NAME" \
  --network "$NETWORK" --ip 172.30.32.3 \
  --volume "$DATA_DIR:/data" \
  --env GATEWAY_TOKEN="$TOKEN" \
  --env HA_SWITCHBOARD_INGRESS_ONLY=true \
  "${SECURITY_OPT[@]}" "$IMAGE" >/dev/null
CONTAINER_CREATED=true

request_code() {
  local client_ip="$1" path="$2" supplied_token="${3:-}"
  "$ENGINE" run --rm --network "$NETWORK" --ip "$client_ip" --entrypoint python3 "$IMAGE" -c '
import sys, urllib.error, urllib.request
url = "http://" + sys.argv[1] + sys.argv[2]
headers = {"Authorization": "Bearer " + sys.argv[3]} if sys.argv[3] else {}
try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=3) as response:
        print(response.status)
except urllib.error.HTTPError as error:
    print(error.code)
except urllib.error.URLError:
    print(0)
' 172.30.32.3:8099 "$path" "$supplied_token"
}

wait_for_code() {
  local client_ip="$1" path="$2" expected="$3"
  local observed=""
  for _ in {1..5}; do
    observed="$(request_code "$client_ip" "$path")"
    [[ "$observed" == "$expected" ]] && return 0
    sleep 0.5
  done
  echo "${client_ip} ${path} did not return HTTP ${expected} (last: ${observed:-none})" >&2
  return 1
}

wait_for_code 172.30.32.2 /healthz 200
container_user="$($ENGINE exec "$RUN_NAME" awk '/^Uid:/ {print $2}' /proc/1/status):$($ENGINE exec "$RUN_NAME" awk '/^Gid:/ {print $2}' /proc/1/status)"
[[ "$container_user" == "65532:65532" ]] || { echo "runtime user mismatch: $container_user" >&2; exit 1; }
[[ "$(request_code 172.30.32.4 /)" == 403 ]] || { echo "direct UI was not rejected" >&2; exit 1; }
[[ "$(request_code 172.30.32.4 /healthz)" == 200 ]] || { echo "healthz failed" >&2; exit 1; }
[[ "$(request_code 172.30.32.4 /readyz)" == 503 ]] || { echo "empty-data readyz was not degraded" >&2; exit 1; }
[[ "$(request_code 172.30.32.4 /v1/profile/status)" == 401 ]] || { echo "unauthenticated API was not rejected" >&2; exit 1; }
[[ "$(request_code 172.30.32.4 /v1/profile/status "$TOKEN")" == 200 ]] || { echo "token-authenticated API failed" >&2; exit 1; }
[[ "$(request_code 172.30.32.2 /)" == 200 ]] || { echo "Supervisor ingress UI failed" >&2; exit 1; }
[[ "$(request_code 172.30.32.2 /healthz)" == 200 ]] || { echo "Supervisor ingress health failed" >&2; exit 1; }

run_hook() {
  local kind="$1" hook="$2"
  [[ -z "$hook" ]] && return 0
  env -i PATH="${PATH:-/usr/bin:/bin}" \
    HA_SWITCHBOARD_E2E_KIND="$kind" \
    HA_SWITCHBOARD_E2E_IMAGE="$IMAGE" \
    HA_SWITCHBOARD_E2E_CONTAINER="$RUN_NAME" \
    HA_SWITCHBOARD_E2E_NETWORK="$NETWORK" \
    HA_SWITCHBOARD_E2E_DATA_DIR="$DATA_DIR" \
    HA_SWITCHBOARD_E2E_SOURCE_ROOT="$ROOT_DIR" \
    HA_SWITCHBOARD_E2E_DISCOVERY_HOOK=1 \
    bash -c "$hook"
}
run_hook supervisor-discovery "$SUPERVISOR_HOOK"
run_hook integration-e2e "$INTEGRATION_HOOK"

echo "PASS: local source build, non-root runtime, AppArmor option, ingress, and token API contract"
