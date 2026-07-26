#!/usr/bin/env bash
set -euo pipefail

: "${AI_SERVICE_TOKEN:?AI_SERVICE_TOKEN must be configured}"
: "${REDIS_URL:?REDIS_URL must be configured}"
: "${AI_FEATURE_STORE_DIR:?AI_FEATURE_STORE_DIR must be configured}"
: "${AI_MODEL_DIR:?AI_MODEL_DIR must be configured}"

require_path() {
  local variable_name="$1"
  local configured_path="$2"
  local required_path="$3"
  if [[ "$configured_path" != "$required_path" ]]; then
    echo "$variable_name must be $required_path (received: $configured_path)" >&2
    exit 64
  fi
}

require_path "AI_FEATURE_STORE_DIR" "$AI_FEATURE_STORE_DIR" "/app/storage/user_data"
require_path "AI_MODEL_DIR" "$AI_MODEL_DIR" "/app/storage/models"
mkdir -p "$AI_FEATURE_STORE_DIR" "$AI_MODEL_DIR"

worker_pid=""
api_pid=""

stop_children() {
  trap - EXIT TERM INT
  if [[ -n "$worker_pid" ]]; then
    kill -TERM "$worker_pid" 2>/dev/null || true
  fi
  if [[ -n "$api_pid" ]]; then
    kill -TERM "$api_pid" 2>/dev/null || true
  fi
  if [[ -n "$worker_pid" ]]; then
    wait "$worker_pid" 2>/dev/null || true
  fi
  if [[ -n "$api_pid" ]]; then
    wait "$api_pid" 2>/dev/null || true
  fi
}

handle_signal() {
  stop_children
  exit 143
}

trap stop_children EXIT
trap handle_signal TERM INT

python -m worker.worker &
worker_pid=$!

python -m app.serve &
api_pid=$!

set +e
wait -n "$worker_pid" "$api_pid"
exit_status=$?
set -e

# A clean exit from either long-running process is still unexpected. Returning
# non-zero lets Railway apply the configured ON_FAILURE restart policy.
if [[ "$exit_status" -eq 0 ]]; then
  exit_status=1
fi

stop_children
exit "$exit_status"
