#!/usr/bin/env bash
set -Eeuo pipefail

# Run the Home Assistant Apps Supervisor harness locally without changing the
# release manifest. The staging copy is disposable and has the image: key
# removed so Supervisor builds the App from the local Dockerfile.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_KEY="$(printf '%s' "$ROOT_DIR" | sha256sum | cut -c1-12)"
STAGE_DIR="${TMPDIR:-/tmp}/ha-switchboard-local-${ROOT_KEY}"
APP_SLUG="local_ha_switchboard"
WAIT_SECONDS="${HA_SWITCHBOARD_WAIT_SECONDS:-180}"
LOCAL_HA_URL="${HA_SWITCHBOARD_LOCAL_HA_URL:-http://127.0.0.1:7123/}"
LOCAL_OBSERVER_URL="${HA_SWITCHBOARD_LOCAL_OBSERVER_URL:-http://127.0.0.1:7357/}"
HACS_REPOSITORY_URL="https://github.com/hacs/addons"
LOCAL_CORE_CONFIG_DIR="/mnt/supervisor/homeassistant"
LOCAL_OPTIONS_FILE="$ROOT_DIR/.env.local"

load_local_test_options() {
  [[ -f "$LOCAL_OPTIONS_FILE" ]] || return 0
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ ! "$line" =~ ^([A-Z_]+)=(.*)$ ]]; then
      echo "Invalid local options line (expected NAME=value)." >&2
      return 2
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    case "$key" in
      HA_SWITCHBOARD_JEV_ENDPOINT|HA_SWITCHBOARD_JEV_API_KEY|HA_SWITCHBOARD_GATEWAY_TOKEN|HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES|HA_SWITCHBOARD_PRIVACY_MODE) ;;
      *) echo "Unsupported local option name: $key" >&2; return 2 ;;
    esac
    if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    # Explicitly exported values win; this parser never evaluates shell code.
    if [[ ! -v "$key" ]]; then
      export "$key=$value"
    fi
  done < "$LOCAL_OPTIONS_FILE"
}

usage() {
  cat <<'EOF'
Usage: tools/local-dev.sh <command>

Commands:
  check       Run compile, unit, release-boundary, and image smoke checks.
  up          Sync a disposable local-build copy and start the App devcontainer.
  start-ha    Start the local Supervisor/Home Assistant process (foreground).
  wait        Wait for Supervisor and the local Home Assistant endpoints.
  store       Refresh the local App store and show HA Switchboard metadata.
  install     Install and start the locally built HA Switchboard App.
  configure   Apply exported HA_SWITCHBOARD_* test options to the local App.
  start       Start the locally built HA Switchboard App.
  rebuild     Rebuild and restart the locally built App after source changes.
  install-hacs
              Install HACS through its official Home Assistant App Store app.
  sync-integration
              Copy the current worktree integration into the local Core config.
  e2e         Run the local Supervisor, Home Assistant, and App ingress checks.
  logs        Follow the local App logs.
  stop        Stop the local App.
  down        Remove the devcontainer only with HA_SWITCHBOARD_ALLOW_DEV_RESET=1.
  clean       Remove the devcontainer and staging copy only with that guard.

The staging copy is used because the release app/config.yaml intentionally
contains image: ghcr.io/...; Home Assistant requires image: to be absent for
local Supervisor builds. Source edits remain in the real worktree.

For configure/e2e, these variables may be exported or placed as literal
NAME=value lines in ignored .env.local (exported values win): HA_SWITCHBOARD_JEV_ENDPOINT,
HA_SWITCHBOARD_JEV_API_KEY, HA_SWITCHBOARD_GATEWAY_TOKEN,
HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES, HA_SWITCHBOARD_PRIVACY_MODE.
Values are passed through the process environment, never written to this tree.
The Supervisor/Core data lives in a Docker volume. Removing the devcontainer
can detach that volume and make a new local Home Assistant appear unconfigured.
Take a verified volume snapshot before using down or clean.
EOF
}

run_devcontainer() {
  if command -v devcontainer >/dev/null 2>&1; then
    devcontainer "$@"
  else
    npx --yes @devcontainers/cli "$@"
  fi
}

run_in_container() {
  run_devcontainer exec --workspace-folder "$STAGE_DIR" "$@"
}

container_workspace_dir() {
  printf '/mnt/supervisor/apps/local/%s\n' "$(basename "$STAGE_DIR")"
}

run_in_container_root() {
  local container_id
  container_id="$(devcontainer_id)"
  [[ -n "$container_id" ]] || {
    echo "The local App devcontainer is not running." >&2
    return 1
  }
  docker exec --user 0 \
    -e "WORKSPACE_DIRECTORY=$(container_workspace_dir)" \
    "$container_id" "$@"
}

devcontainer_id() {
  docker ps -aq --filter "label=devcontainer.local_folder=$STAGE_DIR" | head -n 1
}

remove_devcontainer() {
  local container_id
  container_id="$(devcontainer_id)"
  [[ -n "$container_id" ]] || return 0
  docker rm -f "$container_id" >/dev/null
}

require_dev_reset_guard() {
  if [[ "${HA_SWITCHBOARD_ALLOW_DEV_RESET:-}" != "1" ]]; then
    echo "Refusing to remove the devcontainer: its Supervisor/Core data is in a Docker volume." >&2
    echo "Take a verified snapshot, then set HA_SWITCHBOARD_ALLOW_DEV_RESET=1 if removal is intentional." >&2
    return 1
  fi
}

wait_for_supervisor() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  echo "Waiting for local Supervisor readiness (up to ${WAIT_SECONDS}s)..." >&2
  while (( SECONDS < deadline )); do
    if run_in_container sh -lc \
      "ha supervisor info --raw-json 2>/dev/null | jq -e '.data.healthy == true' >/dev/null" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Local Supervisor did not become healthy within ${WAIT_SECONDS}s." >&2
  echo "Run 'tools/local-dev.sh start-ha' in another terminal and retry." >&2
  return 1
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local deadline=$((SECONDS + WAIT_SECONDS))
  local status="000"
  echo "Waiting for ${label} at ${url}..." >&2
  while (( SECONDS < deadline )); do
    status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || true)"
    if [[ "$status" =~ ^[23][0-9][0-9]$ ]]; then
      return 0
    fi
    sleep 2
  done
  echo "${label} did not become reachable (last HTTP status ${status})." >&2
  return 1
}

app_state() {
  run_in_container sh -lc \
    "ha apps info --raw-json '$APP_SLUG' 2>/dev/null | jq -r '.data.state // empty'"
}

wait_for_app_started() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  local state=""
  echo "Waiting for ${APP_SLUG} to reach started state..." >&2
  while (( SECONDS < deadline )); do
    state="$(app_state 2>/dev/null || true)"
    if [[ "$state" == "started" ]]; then
      return 0
    fi
    if [[ "$state" == "error" ]]; then
      echo "${APP_SLUG} entered Supervisor error state." >&2
      return 1
    fi
    sleep 2
  done
  echo "${APP_SLUG} did not reach started state (last state: ${state:-unknown})." >&2
  return 1
}

  wait_for_app_ingress() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  echo "Waiting for ${APP_SLUG} ingress health..." >&2
  while (( SECONDS < deadline )); do
    # The nested shell must expand app_ip after it inspects the local App.
    # shellcheck disable=SC2016
    if run_in_container sh -lc '
      set -eu
      app="$(docker ps -q --filter name=app_local_ha_switchboard | head -n 1)"
      test -n "$app"
      app_ip="$(docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" "$app")"
      docker exec hassio_supervisor python3 -c "import json,urllib.request; r=urllib.request.urlopen(\"http://$app_ip:8099/healthz\"); body=json.load(r); assert r.status == 200 and body.get(\"status\") == \"ok\""
    ' >/dev/null 2>&1; then
      echo "${APP_SLUG} ingress health passed." >&2
      return 0
    fi
    sleep 2
  done
  echo "${APP_SLUG} did not pass the Supervisor-source ingress health check." >&2
  return 1
}

install_app() {
  run_in_container sh -lc "set -e; ha store reload; result=\$(ha apps install --raw-json '$APP_SLUG'); if printf '%s\\n' \"\$result\" | jq -e '.result == \"error\" and .error_key != \"app_already_installed_error\"' >/dev/null; then printf '%s\\n' \"\$result\" >&2; exit 1; fi; ha apps start '$APP_SLUG'"
}

has_local_options_env() {
  [[ -n "${HA_SWITCHBOARD_JEV_ENDPOINT:-}${HA_SWITCHBOARD_JEV_API_KEY:-}${HA_SWITCHBOARD_GATEWAY_TOKEN:-}${HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES:-}${HA_SWITCHBOARD_PRIVACY_MODE:-}" ]]
}

configure_app() {
  local container_id
  container_id="$(devcontainer_id)"
  [[ -n "$container_id" ]] || { echo "The local App devcontainer is not running." >&2; return 1; }
  # Core has a scoped Supervisor token; only it can read the current options.
  # Docker -e NAME forwards exported values without embedding secrets in this
  # script, its arguments, or its output. The Core process is not restarted.
  docker exec -i \
    -e HA_SWITCHBOARD_JEV_ENDPOINT \
    -e HA_SWITCHBOARD_JEV_API_KEY \
    -e HA_SWITCHBOARD_GATEWAY_TOKEN \
    -e HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES \
    -e HA_SWITCHBOARD_PRIVACY_MODE \
    "$container_id" sh -lc '
      docker exec -i \
        -e HA_SWITCHBOARD_JEV_ENDPOINT \
        -e HA_SWITCHBOARD_JEV_API_KEY \
        -e HA_SWITCHBOARD_GATEWAY_TOKEN \
        -e HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES \
        -e HA_SWITCHBOARD_PRIVACY_MODE \
        homeassistant python3 -
    ' <<'PY'
import json
import os
from urllib.request import Request, urlopen

base = "http://supervisor/addons/local_ha_switchboard"
headers = {
    "Authorization": "Bearer " + os.environ["SUPERVISOR_TOKEN"],
    "Content-Type": "application/json",
}
with urlopen(Request(base + "/info", headers=headers), timeout=10) as response:
    options = dict(json.load(response)["data"]["options"])

names = {
    "HA_SWITCHBOARD_JEV_ENDPOINT": "jev_endpoint",
    "HA_SWITCHBOARD_JEV_API_KEY": "jev_api_key",
    "HA_SWITCHBOARD_GATEWAY_TOKEN": "gateway_token",
    "HA_SWITCHBOARD_PRIVACY_MODE": "privacy_mode",
}
for environment_name, option_name in names.items():
    if value := os.environ.get(environment_name):
        options[option_name] = value

if minutes := os.environ.get("HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES"):
    value = int(minutes)
    if not 1 <= value <= 1440:
        raise ValueError("profile refresh minutes must be 1..1440")
    options["profile_refresh_minutes"] = value

if options.get("privacy_mode") not in {"local_only", "jev_hosted_allowed", "hosted_allowed"}:
    raise ValueError("invalid privacy mode")
if not options.get("gateway_token"):
    raise ValueError("a gateway token is required for the Core integration")

payload = json.dumps({"options": options}).encode()
with urlopen(Request(base + "/options", data=payload, headers=headers, method="POST"), timeout=20) as response:
    result = json.load(response)
if result.get("result") != "ok":
    raise RuntimeError("Supervisor rejected the local App options")
print("Local App options applied without printing credentials.")
PY
  run_in_container ha apps restart "$APP_SLUG" >/dev/null
  wait_for_app_started
}

hacs_repository_slug() {
  run_in_container sh -lc \
    "ha store info --raw-json | jq -r --arg url '$HACS_REPOSITORY_URL' '.data.repositories[] | select(.source == \$url) | .slug' | head -n 1"
}

ensure_hacs_repository() {
  local repository_slug
  repository_slug="$(hacs_repository_slug)"
  if [[ -z "$repository_slug" ]]; then
    echo "Adding the official HACS App Store repository..." >&2
    run_in_container ha store add "$HACS_REPOSITORY_URL" >/dev/null
    run_in_container ha store reload >/dev/null
    repository_slug="$(hacs_repository_slug)"
  fi
  [[ -n "$repository_slug" ]] || {
    echo "The HACS App Store repository was not available after reload." >&2
    return 1
  }
  printf '%s\n' "$repository_slug"
}

hacs_installed() {
  run_in_container sh -lc \
    "test -f '$LOCAL_CORE_CONFIG_DIR/custom_components/hacs/manifest.json'"
}

wait_for_hacs_download() {
  local app_slug="$1"
  local deadline=$((SECONDS + WAIT_SECONDS))
  local state=""
  echo "Waiting for the Get HACS app to finish writing the HACS integration..." >&2
  while (( SECONDS < deadline )); do
    if hacs_installed >/dev/null 2>&1; then
      return 0
    fi
    state="$(run_in_container sh -lc \
      "ha apps info --raw-json '$app_slug' 2>/dev/null | jq -r '.data.state // empty'" \
      2>/dev/null || true)"
    if [[ "$state" == "error" ]]; then
      echo "The Get HACS app entered Supervisor error state." >&2
      return 1
    fi
    sleep 2
  done
  echo "The Get HACS app did not install the HACS integration within ${WAIT_SECONDS}s." >&2
  return 1
}

install_hacs() {
  wait_for_supervisor
  local repository_slug app_slug
  repository_slug="$(ensure_hacs_repository)"
  app_slug="${repository_slug}_get"

  if hacs_installed >/dev/null 2>&1; then
    echo "HACS is already installed in the disposable local Core config." >&2
    return 0
  fi

  local app_installed app_state_value
  app_installed="$(run_in_container sh -lc \
    "ha store info --raw-json | jq -r --arg slug '$app_slug' '.data.addons[] | select(.slug == \$slug) | .installed'" \
    2>/dev/null || true)"
  if [[ "$app_installed" != "true" ]]; then
    echo "Installing Get HACS from App Store repository ${repository_slug}..." >&2
    run_in_container ha apps install "$app_slug" >/dev/null
  fi
  app_state_value="$(run_in_container sh -lc \
    "ha apps info --raw-json '$app_slug' 2>/dev/null | jq -r '.data.state // empty'" \
    2>/dev/null || true)"
  if [[ "$app_state_value" == "error" ]]; then
    echo "The Get HACS app is in Supervisor error state." >&2
    return 1
  fi
  if [[ "$app_state_value" != "started" ]]; then
    run_in_container ha apps start "$app_slug" >/dev/null
  fi
  wait_for_hacs_download "$app_slug"

  echo "Restarting Home Assistant Core so it can discover HACS..." >&2
  run_in_container ha core restart >/dev/null
  wait_for_http "$LOCAL_HA_URL" "Home Assistant after HACS installation"
  echo "HACS is ready. Configure it in Settings > Devices & services > Add integration." >&2
}

sync_integration() {
  # Always refresh the disposable copy. Otherwise integration edits made in
  # the real worktree are silently absent once the stage directory exists.
  sync_stage
  wait_for_supervisor
  # The variables below must expand inside the container, not on the host.
  # shellcheck disable=SC2016
  run_in_container_root sh -lc '
    set -eu
    source_dir="$WORKSPACE_DIRECTORY/custom_components/ha_switchboard"
    target_dir="/mnt/supervisor/homeassistant/custom_components/ha_switchboard"
    test -f "$source_dir/manifest.json"
    mkdir -p "$(dirname "$target_dir")"
    rsync -a --delete \
      --exclude __pycache__ \
      --exclude "*.pyc" \
      "$source_dir/" "$target_dir/"
  '
  echo "Restarting Home Assistant Core with the current worktree integration..." >&2
  run_in_container ha core restart >/dev/null
  wait_for_http "$LOCAL_HA_URL" "Home Assistant after integration sync"
  echo "Current worktree integration is available at ${LOCAL_CORE_CONFIG_DIR}/custom_components/ha_switchboard." >&2
}

sync_stage() {
  command -v rsync >/dev/null 2>&1 || {
    echo "rsync is required for the local Supervisor staging copy" >&2
    exit 2
  }

  mkdir -p "$STAGE_DIR"
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '.pytest_cache' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    "$ROOT_DIR/" "$STAGE_DIR/"

  # Do not alter the real release manifest. The official Home Assistant local
  # build path is selected by omitting image from the staged config.
  sed -i '/^image: "ghcr\.io\/grayslawson\/ha-switchboard"$/s/^/# image: /' \
    "$STAGE_DIR/app/config.yaml"
}

case "${1:-help}" in
  configure|e2e) load_local_test_options ;;
esac

case "${1:-help}" in
  check)
    python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
    python3 -m pytest -q tests
    python3 tools/check_release_boundary.py
    bash tools/app-image-smoke.sh
    ;;
  up)
    sync_stage
    run_devcontainer up --workspace-folder "$STAGE_DIR" --log-level info
    ;;
  start-ha)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    run_in_container supervisor_run
    ;;
  wait)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    wait_for_supervisor
    wait_for_http "$LOCAL_HA_URL" "Home Assistant"
    wait_for_http "$LOCAL_OBSERVER_URL" "Supervisor observer"
    ;;
  store)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    wait_for_supervisor
    run_in_container sh -lc "ha store reload && ha store info --raw-json | jq '.data.addons[] | select(.slug == \"$APP_SLUG\")'"
    ;;
  install)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    wait_for_supervisor
    install_app
    wait_for_app_started
    ;;
  install-hacs)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    install_hacs
    ;;
  configure)
    wait_for_supervisor
    configure_app
    ;;
  sync-integration)
    sync_integration
    ;;
  start)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    wait_for_supervisor
    run_in_container ha apps start "$APP_SLUG"
    wait_for_app_started
    ;;
  rebuild)
    [[ -n "$(devcontainer_id)" ]] || {
      echo "No existing devcontainer found; refusing to create a fresh Home Assistant during rebuild." >&2
      exit 1
    }
    sync_stage
    wait_for_supervisor
    run_in_container sh -lc "ha apps stop '$APP_SLUG' >/dev/null 2>&1 || true; ha apps rebuild --force '$APP_SLUG'; ha apps start '$APP_SLUG'"
    wait_for_app_started
    ;;
  e2e)
    sync_stage
    wait_for_supervisor
    wait_for_http "$LOCAL_HA_URL" "Home Assistant"
    wait_for_http "$LOCAL_OBSERVER_URL" "Supervisor observer"
    run_in_container sh -lc "ha store reload"
    state="$(app_state 2>/dev/null || true)"
    if [[ "$state" != "started" ]]; then
      install_app
    fi
    wait_for_app_started
    if has_local_options_env; then
      configure_app
    fi
    wait_for_app_ingress
    echo "Local HA Switchboard E2E checks passed."
    ;;
  logs)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    run_in_container ha apps logs -f "$APP_SLUG"
    ;;
  stop)
    [[ -d "$STAGE_DIR" ]] || exit 0
    run_in_container ha apps stop "$APP_SLUG"
    ;;
  down)
    require_dev_reset_guard
    [[ -d "$STAGE_DIR" ]] || exit 0
    run_in_container sh -lc "ha apps stop '$APP_SLUG' >/dev/null 2>&1 || true" || true
    remove_devcontainer
    ;;
  clean)
    require_dev_reset_guard
    [[ -d "$STAGE_DIR" ]] || exit 0
    run_in_container sh -lc "ha apps stop '$APP_SLUG' >/dev/null 2>&1 || true" || true
    remove_devcontainer
    rm -rf -- "$STAGE_DIR"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "unknown local-dev command: $1" >&2
    usage >&2
    exit 2
    ;;
esac
