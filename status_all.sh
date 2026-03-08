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

print_service_status() {
  local name="$1"
  local url="$2"
  local pid_file="$3"
  local log_file="$4"

  echo "=============================="
  echo "$name"
  echo "- URL: $url"
  echo "- PID 文件: $pid_file"
  echo "- 日志文件: $log_file"

  local pid=""
  if pid="$(check_pid "$pid_file")"; then
    echo "- 进程状态: 运行中 (PID: $pid)"
  else
    echo "- 进程状态: 未发现有效 PID"
  fi

  local body=""
  if body="$(health_body "$url" 2>/dev/null)"; then
    echo "- 健康检查: 正常"
    echo "- 健康响应: $body"
    return 0
  fi

  echo "- 健康检查: 失败"
  if [[ -f "$log_file" ]]; then
    echo "- 最近日志:"
    tail -n 5 "$log_file" || true
  fi
  return 1
}

ALL_OK=0

if print_service_status "ESM3 常驻服务" "http://${SERVER_HOST}:${SERVER_PORT}/health" "$ESM3_PID_FILE" "$ESM3_LOG"; then
  :
else
  ALL_OK=1
fi

if print_service_status "Protein Agent API" "http://${API_HOST}:${API_PORT}/health" "$AGENT_PID_FILE" "$AGENT_LOG"; then
  :
else
  ALL_OK=1
fi

echo "=============================="
if [[ "$ALL_OK" -eq 0 ]]; then
  echo "总结：两个服务都正常。"
else
  echo "总结：至少有一个服务异常，请结合上面的日志继续排查。"
fi

exit "$ALL_OK"
