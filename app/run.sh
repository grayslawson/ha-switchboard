#!/bin/sh
set -eu
umask 077

DATA_DIR="${JEV_DATA_DIR:-/data}"
PORT="${JEV_PORT:-8099}"
case "$DATA_DIR" in
  /data|/data/*)
    case "$DATA_DIR" in
      *..*) echo "data directory must not contain parent traversal: $DATA_DIR" >&2; exit 1 ;;
    esac
    ;;
  *) echo "data directory must remain under /data" >&2; exit 1 ;;
esac
case "$PORT" in
  [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|\
  [1-5][0-9][0-9][0-9][0-9]|6[0-4][0-9][0-9][0-9]|65[0-4][0-9][0-9]|\
  655[0-2][0-9]|6553[0-5]) ;;
  *) echo "port must be a decimal value from 1 to 65535: $PORT" >&2; exit 1 ;;
esac
if [ ! -d "$DATA_DIR" ]; then
  echo "data directory does not exist: $DATA_DIR" >&2
  exit 1
fi
exec /usr/local/bin/python3 -m ha_switchboard.server \
  --data-dir "$DATA_DIR" \
  --host "${JEV_HOST:-0.0.0.0}" \
  --port "$PORT"
