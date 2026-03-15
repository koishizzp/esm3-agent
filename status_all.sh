#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

SERVER_HOST="${PROTEIN_AGENT_ESM3_SERVER_HOST:-127.0.0.1}"
SERVER_PORT="${PROTEIN_AGENT_ESM3_SERVER_PORT:-8001}"
API_HOST="${PROTEIN_AGENT_API_HOST:-127.0.0.1}"
API_PORT="${PROTEIN_AGENT_API_PORT:-8000}"
ESM3_PID_FILE="${PROTEIN_AGENT_ESM3_SERVER_PID_FILE:-logs/esm3_server.pid}"
AGENT_PID_FILE="${PROTEIN_AGENT_API_PID_FILE:-logs/protein_agent.pid}"
ESM3_LOG="${PROTEIN_AGENT_ESM3_SERVER_LOG:-logs/esm3_server.log}"
AGENT_LOG="${PROTEIN_AGENT_API_LOG:-logs/protein_agent.log}"

health_body() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$url" 2>/dev/null || return 1
    return 0
  fi

  local python_bin="${PROTEIN_AGENT_ESM3_PYTHON_PATH:-python3}"
  "$python_bin" - "$url" <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=3) as resp:
    print(resp.read().decode("utf-8", errors="replace"))
PY
}

check_pid() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(tr -d '[:space:]' <"$pid_file")"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if kill -0 "$pid" >/dev/null 2>&1; then
    printf '%s' "$pid"
    return 0
  fi
  return 1
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

print_service_status() {
  local name="$1"
  local url="$2"
  local pid_file="$3"
  local log_file="$4"
  local port="$5"
  local owners=""

  echo "=============================="
  echo "$name"
  echo "- URL: $url"
  echo "- PID file: $pid_file"
  echo "- Log file: $log_file"

  local pid=""
  if pid="$(check_pid "$pid_file")"; then
    echo "- Process: running (PID: $pid)"
  else
    echo "- Process: no active PID from the managed pid file"
  fi

  local body=""
  if body="$(health_body "$url" 2>/dev/null)"; then
    owners="$(print_port_owners "$port")"
    if [[ -n "$pid" ]] && ! pid_owns_port "$pid" "$port"; then
      echo "- Port owner: mismatch"
      echo "- Expected PID $pid, but port $port is owned by:"
      echo "$owners"
      return 1
    fi
    if [[ -z "$pid" ]] && [[ -n "$owners" ]]; then
      echo "- Port owner: unmanaged process"
      echo "$owners"
      return 1
    fi
    echo "- Health: ok"
    echo "- Health body: $body"
    return 0
  fi

  echo "- Health: failed"
  owners="$(print_port_owners "$port")"
  if [[ -n "$owners" ]]; then
    echo "- Port listener:"
    echo "$owners"
  fi
  if [[ -f "$log_file" ]]; then
    echo "- Recent log lines:"
    tail -n 5 "$log_file" || true
  fi
  return 1
}

ALL_OK=0

if print_service_status "ESM3 service" "http://${SERVER_HOST}:${SERVER_PORT}/health" "$ESM3_PID_FILE" "$ESM3_LOG" "$SERVER_PORT"; then
  :
else
  ALL_OK=1
fi

if print_service_status "Protein Agent API" "http://${API_HOST}:${API_PORT}/health" "$AGENT_PID_FILE" "$AGENT_LOG" "$API_PORT"; then
  :
else
  ALL_OK=1
fi

echo "=============================="
if [[ "$ALL_OK" -eq 0 ]]; then
  echo "Summary: both managed services are healthy."
else
  echo "Summary: at least one managed service is unhealthy or port ownership does not match."
fi

exit "$ALL_OK"
