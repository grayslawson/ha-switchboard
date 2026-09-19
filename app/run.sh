#!/bin/sh
set -eu

DATA_DIR="${JEV_DATA_DIR:-/data}"
if [ ! -d "$DATA_DIR" ]; then
  echo "data directory does not exist: $DATA_DIR" >&2
  exit 1
fi
exec python3 -m ha_switchboard.server \
  --data-dir "$DATA_DIR" \
  --host "${JEV_HOST:-0.0.0.0}" \
  --port "${JEV_PORT:-8099}"
