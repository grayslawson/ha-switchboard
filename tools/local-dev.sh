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
  start       Start the locally built HA Switchboard App.
  rebuild     Rebuild and restart the locally built App after source changes.
  e2e         Run the local Supervisor, Home Assistant, and App ingress checks.
  logs        Follow the local App logs.
  stop        Stop the local App.
  down        Stop the devcontainer and its local Supervisor.
  clean       Remove the disposable staging copy after stopping the container.

The staging copy is used because the release app/config.yaml intentionally
contains image: ghcr.io/...; Home Assistant requires image: to be absent for
local Supervisor builds. Source edits remain in the real worktree.
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

devcontainer_id() {
  docker ps -aq --filter "label=devcontainer.local_folder=$STAGE_DIR" | head -n 1
}

remove_devcontainer() {
  local container_id
  container_id="$(devcontainer_id)"
  [[ -n "$container_id" ]] || return 0
  docker rm -f "$container_id" >/dev/null
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

sync_stage() {
  command -v rsync >/dev/null 2>&1 || {
    echo "rsync is required for the local Supervisor staging copy" >&2
    exit 2
  }

  mkdir -p "$STAGE_DIR"
  rsync -a --delete \
    --exclude '.git' \
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
  start)
    [[ -d "$STAGE_DIR" ]] || sync_stage
    wait_for_supervisor
    run_in_container ha apps start "$APP_SLUG"
    wait_for_app_started
    ;;
  rebuild)
    sync_stage
    run_devcontainer up --workspace-folder "$STAGE_DIR" --log-level info >/dev/null
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
    [[ -d "$STAGE_DIR" ]] || exit 0
    run_in_container sh -lc "ha apps stop '$APP_SLUG' >/dev/null 2>&1 || true" || true
    remove_devcontainer
    ;;
  clean)
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
