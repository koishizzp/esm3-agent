#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

mkdir -p logs

SERVER_HOST="${PROTEIN_AGENT_ESM3_SERVER_HOST:-0.0.0.0}"
SERVER_PORT="${PROTEIN_AGENT_ESM3_SERVER_PORT:-8001}"
API_HOST="${PROTEIN_AGENT_API_HOST:-0.0.0.0}"
API_PORT="${PROTEIN_AGENT_API_PORT:-8000}"
WAIT_TIMEOUT="${PROTEIN_AGENT_START_WAIT_TIMEOUT:-180}"
ESM3_LOG="${PROTEIN_AGENT_ESM3_SERVER_LOG:-logs/esm3_server.log}"
AGENT_LOG="${PROTEIN_AGENT_API_LOG:-logs/protein_agent.log}"
ESM3_PID_FILE="${PROTEIN_AGENT_ESM3_SERVER_PID_FILE:-logs/esm3_server.pid}"
AGENT_PID_FILE="${PROTEIN_AGENT_API_PID_FILE:-logs/protein_agent.pid}"

export PROTEIN_AGENT_ESM3_BACKEND="http"
export PROTEIN_AGENT_ESM3_SERVER_URL="http://127.0.0.1:${SERVER_PORT}"

ESM3_PID=""
AGENT_PID=""

cleanup() {
  local code=$?
  trap - EXIT INT TERM

  if [[ -n "$AGENT_PID" ]] && kill -0 "$AGENT_PID" >/dev/null 2>&1; then
    kill "$AGENT_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$ESM3_PID" ]] && kill -0 "$ESM3_PID" >/dev/null 2>&1; then
    kill "$ESM3_PID" >/dev/null 2>&1 || true
  fi

  wait "$AGENT_PID" >/dev/null 2>&1 || true
  wait "$ESM3_PID" >/dev/null 2>&1 || true

  rm -f "$AGENT_PID_FILE" "$ESM3_PID_FILE"

  exit "$code"
}

health_check() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$url" >/dev/null 2>&1
    return $?
  fi

  local python_bin="${PROTEIN_AGENT_ESM3_PYTHON_PATH:-python3}"
  "$python_bin" - "$url" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=3) as resp:
    if 200 <= getattr(resp, "status", 0) < 300:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

listening_pids_on_port() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk '!seen[$0]++'
    return 0
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v port="$port" '
      $1 == "LISTEN" && index($4, ":" port) {
        if (match($0, /pid=[0-9]+/)) {
          pid = substr($0, RSTART + 4, RLENGTH - 4)
          if (!seen[pid]++) {
            print pid
          }
        }
      }
    '
    return 0
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -ltnp 2>/dev/null | awk -v port="$port" '
      index($4, ":" port) {
        split($7, parts, "/")
        pid = parts[1]
        if (pid ~ /^[0-9]+$/ && !seen[pid]++) {
          print pid
        }
      }
    '
  fi
}

describe_pid() {
  local pid="$1"
  local cmd=""

  if command -v ps >/dev/null 2>&1; then
    cmd="$(ps -p "$pid" -o command= 2>/dev/null | sed 's/^[[:space:]]*//')"
  fi

  if [[ -z "$cmd" ]] && [[ -r "/proc/$pid/cmdline" ]]; then
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | sed 's/[[:space:]]*$//')"
  fi

  printf '%s' "$cmd"
}

print_port_owners() {
  local port="$1"
  local pid=""
  local cmd=""

  while read -r pid; do
    [[ -n "$pid" ]] || continue
    cmd="$(describe_pid "$pid")"
    if [[ -n "$cmd" ]]; then
      echo "  - PID $pid: $cmd"
    else
      echo "  - PID $pid"
    fi
  done < <(listening_pids_on_port "$port")
}

pid_owns_port() {
  local pid="$1"
  local port="$2"
  local owner=""

  while read -r owner; do
    [[ -n "$owner" ]] || continue
    if [[ "$owner" == "$pid" ]]; then
      return 0
    fi
  done < <(listening_pids_on_port "$port")

  return 1
}

ensure_port_available() {
  local name="$1"
  local port="$2"
  local owners=""

  owners="$(print_port_owners "$port")"
  if [[ -z "$owners" ]]; then
    return 0
  fi

  echo "ERROR: cannot start $name because port $port is already in use." >&2
  echo "$owners" >&2
  return 1
}

wait_for_service() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local pid="$4"
  local port="$5"
  local owners=""

  for ((i=1; i<=timeout; i++)); do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "ERROR: $name process exited before it became ready." >&2
      return 1
    fi

    if health_check "$url"; then
      if [[ -z "$pid" ]] || pid_owns_port "$pid" "$port"; then
        echo "$name ready: $url"
        return 0
      fi

      owners="$(print_port_owners "$port")"
      if [[ -n "$owners" ]]; then
        echo "ERROR: health check for $name matched another process on port $port." >&2
        echo "$owners" >&2
      else
        echo "ERROR: health check for $name passed, but PID $pid is not listening on port $port." >&2
      fi
      return 1
    fi

    sleep 1
  done

  echo "ERROR: timed out waiting for $name after ${timeout}s: $url" >&2
  return 1
}

trap cleanup EXIT INT TERM

echo "Starting local ESM3 service..."
ensure_port_available "ESM3 service" "$SERVER_PORT"
bash ./start_esm3_server.sh >"$ESM3_LOG" 2>&1 &
ESM3_PID=$!
echo "$ESM3_PID" >"$ESM3_PID_FILE"

if ! wait_for_service "ESM3 service" "http://127.0.0.1:${SERVER_PORT}/health" "$WAIT_TIMEOUT" "$ESM3_PID" "$SERVER_PORT"; then
  echo "Recent ESM3 log output:"
  tail -n 50 "$ESM3_LOG" || true
  exit 1
fi

echo "Starting Protein Agent API..."
ensure_port_available "Protein Agent API" "$API_PORT"
bash ./start_agent.sh >"$AGENT_LOG" 2>&1 &
AGENT_PID=$!
echo "$AGENT_PID" >"$AGENT_PID_FILE"

if ! wait_for_service "Protein Agent API" "http://127.0.0.1:${API_PORT}/health" "$WAIT_TIMEOUT" "$AGENT_PID" "$API_PORT"; then
  echo "Recent Agent log output:"
  tail -n 50 "$AGENT_LOG" || true
  exit 1
fi

echo
echo "All services started:"
echo "- ESM3 service:  http://127.0.0.1:${SERVER_PORT}"
echo "- Agent API:     http://127.0.0.1:${API_PORT}"
echo "- ESM3 log:      $ESM3_LOG"
echo "- Agent log:     $AGENT_LOG"
echo "- ESM3 PID:      $ESM3_PID_FILE"
echo "- Agent PID:     $AGENT_PID_FILE"
echo
echo "Press Ctrl-C to stop both services."

set +e
wait -n "$ESM3_PID" "$AGENT_PID"
STATUS=$?
set -e

echo "Detected that one service exited; cleaning up the remaining process..."
exit "$STATUS"
