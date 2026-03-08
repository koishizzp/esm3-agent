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
HOST="${PROTEIN_AGENT_ESM3_SERVER_HOST:-0.0.0.0}"
PORT="${PROTEIN_AGENT_ESM3_SERVER_PORT:-8001}"
RUNTIME_DIR="${PROTEIN_AGENT_ESM3_ROOT:-$ROOT_DIR}"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "错误：未设置 PROTEIN_AGENT_ESM3_PYTHON_PATH" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "错误：Python 不可执行：$PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -d "$RUNTIME_DIR" ]]; then
  echo "错误：运行目录不存在：$RUNTIME_DIR" >&2
  exit 1
fi

export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
cd "$RUNTIME_DIR"

echo "启动本地 ESM3 常驻服务..."
echo "项目目录: $ROOT_DIR"
echo "运行目录: $RUNTIME_DIR"
echo "Python: $PYTHON_BIN"
echo "ESM3_ROOT: ${PROTEIN_AGENT_ESM3_ROOT:-}"
echo "监听地址: http://$HOST:$PORT"

exec "$PYTHON_BIN" -m uvicorn protein_agent.esm3_server.server:app --host "$HOST" --port "$PORT"
