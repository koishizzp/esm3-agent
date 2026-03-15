#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

PYTHON_BIN="${PROTEIN_AGENT_ESM3_PYTHON_PATH:-}"
HOST="${PROTEIN_AGENT_API_HOST:-0.0.0.0}"
PORT="${PROTEIN_AGENT_API_PORT:-8002}"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "错误：未设置 PROTEIN_AGENT_ESM3_PYTHON_PATH" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "错误：Python 不可执行：$PYTHON_BIN" >&2
  exit 1
fi

if [[ -z "${PROTEIN_AGENT_ESM3_BACKEND:-}" ]]; then
  export PROTEIN_AGENT_ESM3_BACKEND="http"
fi

if [[ "$PROTEIN_AGENT_ESM3_BACKEND" == "http" && -z "${PROTEIN_AGENT_ESM3_SERVER_URL:-}" ]]; then
  export PROTEIN_AGENT_ESM3_SERVER_URL="http://127.0.0.1:8001"
fi

echo "启动 Protein Agent API..."
echo "项目目录: $ROOT_DIR"
echo "Python: $PYTHON_BIN"
echo "ESM3_BACKEND: ${PROTEIN_AGENT_ESM3_BACKEND:-}"
echo "ESM3_SERVER_URL: ${PROTEIN_AGENT_ESM3_SERVER_URL:-}"
echo "监听地址: http://$HOST:$PORT"

exec "$PYTHON_BIN" -m uvicorn protein_agent.api.main:app --host "$HOST" --port "$PORT"
