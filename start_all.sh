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

wait_for_service() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local pid="$4"

  for ((i=1; i<=timeout; i++)); do
    if health_check "$url"; then
      echo "$name 已就绪: $url"
      return 0
    fi
    if [[ -n "$pid" ]] && ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "错误：$name 进程提前退出" >&2
      return 1
    fi
    sleep 1
  done

  echo "错误：等待 $name 超时（${timeout}s）: $url" >&2
  return 1
}

trap cleanup EXIT INT TERM

echo "启动本地 ESM3 常驻服务..."
bash ./start_esm3_server.sh >"$ESM3_LOG" 2>&1 &
ESM3_PID=$!
echo "$ESM3_PID" >"$ESM3_PID_FILE"

if ! wait_for_service "ESM3 服务" "http://127.0.0.1:${SERVER_PORT}/health" "$WAIT_TIMEOUT" "$ESM3_PID"; then
  echo "最近的 ESM3 日志："
  tail -n 50 "$ESM3_LOG" || true
  exit 1
fi

echo "启动 Protein Agent API..."
bash ./start_agent.sh >"$AGENT_LOG" 2>&1 &
AGENT_PID=$!
echo "$AGENT_PID" >"$AGENT_PID_FILE"

if ! wait_for_service "Agent API" "http://127.0.0.1:${API_PORT}/health" "$WAIT_TIMEOUT" "$AGENT_PID"; then
  echo "最近的 Agent 日志："
  tail -n 50 "$AGENT_LOG" || true
  exit 1
fi

echo
echo "全部服务已启动："
echo "- ESM3 服务:  http://127.0.0.1:${SERVER_PORT}"
echo "- Agent API:  http://127.0.0.1:${API_PORT}"
echo "- ESM3 日志:  $ESM3_LOG"
echo "- Agent 日志: $AGENT_LOG"
echo "- ESM3 PID:   $ESM3_PID_FILE"
echo "- Agent PID:  $AGENT_PID_FILE"
echo
echo "按 Ctrl-C 可同时停止两个服务。"

set +e
wait -n "$ESM3_PID" "$AGENT_PID"
STATUS=$?
set -e

echo "检测到有服务退出，正在清理其余进程..."
exit "$STATUS"
