#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

ESM3_PID_FILE="${PROTEIN_AGENT_ESM3_SERVER_PID_FILE:-logs/esm3_server.pid}"
AGENT_PID_FILE="${PROTEIN_AGENT_API_PID_FILE:-logs/protein_agent.pid}"
STOP_TIMEOUT="${PROTEIN_AGENT_STOP_WAIT_TIMEOUT:-20}"

stop_pid() {
  local name="$1"
  local pid="$2"
  local timeout="$3"

  if [[ -z "$pid" ]]; then
    return 1
  fi
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 1
  fi

  echo "停止 $name (PID: $pid)..."
  kill "$pid" >/dev/null 2>&1 || true

  for ((i=1; i<=timeout; i++)); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$name 已停止"
      return 0
    fi
    sleep 1
  done

  echo "$name 在 ${timeout}s 内未退出，发送 SIGKILL..."
  kill -9 "$pid" >/dev/null 2>&1 || true
  sleep 1
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "$name 已强制停止"
    return 0
  fi
  echo "警告：$name 仍未停止 (PID: $pid)" >&2
  return 1
}

read_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d '[:space:]' <"$file"
    return 0
  fi
  return 1
}

find_pid_by_pattern() {
  local pattern="$1"
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -f "$pattern" | head -n 1
    return 0
  fi
  return 1
}

STOPPED_ANY=0

AGENT_PID="$(read_pid_file "$AGENT_PID_FILE" 2>/dev/null || true)"
if [[ -n "$AGENT_PID" ]] && stop_pid "Agent API" "$AGENT_PID" "$STOP_TIMEOUT"; then
  STOPPED_ANY=1
fi

ESM3_PID="$(read_pid_file "$ESM3_PID_FILE" 2>/dev/null || true)"
if [[ -n "$ESM3_PID" ]] && stop_pid "ESM3 服务" "$ESM3_PID" "$STOP_TIMEOUT"; then
  STOPPED_ANY=1
fi

rm -f "$AGENT_PID_FILE" "$ESM3_PID_FILE"

if [[ "$STOPPED_ANY" -eq 0 ]]; then
  FALLBACK_AGENT_PID="$(find_pid_by_pattern 'uvicorn protein_agent.api.main:app' 2>/dev/null || true)"
  if [[ -n "$FALLBACK_AGENT_PID" ]] && stop_pid "Agent API" "$FALLBACK_AGENT_PID" "$STOP_TIMEOUT"; then
    STOPPED_ANY=1
  fi

  FALLBACK_ESM3_PID="$(find_pid_by_pattern 'uvicorn protein_agent.esm3_server.server:app' 2>/dev/null || true)"
  if [[ -n "$FALLBACK_ESM3_PID" ]] && stop_pid "ESM3 服务" "$FALLBACK_ESM3_PID" "$STOP_TIMEOUT"; then
    STOPPED_ANY=1
  fi
fi

if [[ "$STOPPED_ANY" -eq 0 ]]; then
  echo "未发现由本项目启动的 ESM3/Agent 进程。"
  exit 0
fi

echo "已完成停止。"
