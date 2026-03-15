#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

resolve_host() {
  local host="$1"
  if [[ -z "$host" || "$host" == "0.0.0.0" ]]; then
    printf '127.0.0.1'
    return 0
  fi
  printf '%s' "$host"
}

SERVER_HOST="$(resolve_host "${PROTEIN_AGENT_ESM3_SERVER_HOST:-127.0.0.1}")"
SERVER_PORT="${PROTEIN_AGENT_ESM3_SERVER_PORT:-8001}"
API_HOST="$(resolve_host "${PROTEIN_AGENT_API_HOST:-127.0.0.1}")"
API_PORT="${PROTEIN_AGENT_API_PORT:-8002}"

ESM3_URL="http://${SERVER_HOST}:${SERVER_PORT}"
AGENT_URL="http://${API_HOST}:${API_PORT}"

ESM3_LOG="${PROTEIN_AGENT_ESM3_SERVER_LOG:-logs/esm3_server.log}"
AGENT_LOG="${PROTEIN_AGENT_API_LOG:-logs/protein_agent.log}"

PYTHON_BIN="${PROTEIN_AGENT_ESM3_PYTHON_PATH:-python3}"
SMOKE_SEQUENCE="${PROTEIN_AGENT_SMOKE_SEQUENCE:-MSKGEELFTGVV}"
SMOKE_TASK="${PROTEIN_AGENT_SMOKE_TASK:-Automatically design GFP and iteratively optimize it}"
SMOKE_ITERATIONS="${PROTEIN_AGENT_SMOKE_ITERATIONS:-1}"
SMOKE_CANDIDATES="${PROTEIN_AGENT_SMOKE_CANDIDATES:-2}"

print_section() {
  echo
  echo "=============================="
  echo "$1"
  echo "=============================="
}

show_recent_logs() {
  if [[ -f "$ESM3_LOG" ]]; then
    echo
    echo "[最近的 ESM3 日志]"
    tail -n 20 "$ESM3_LOG" || true
  fi
  if [[ -f "$AGENT_LOG" ]]; then
    echo
    echo "[最近的 Agent 日志]"
    tail -n 20 "$AGENT_LOG" || true
  fi
}

pretty_json() {
  local raw="$1"
  if [[ -z "$raw" ]]; then
    return 0
  fi
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$raw" | jq . 2>/dev/null || printf '%s\n' "$raw"
    return 0
  fi
  "$PYTHON_BIN" - "$raw" <<'PY' 2>/dev/null || printf '%s\n' "$raw"
import json
import sys

text = sys.argv[1]
print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
PY
}

require_field() {
  local raw="$1"
  local field="$2"
  "$PYTHON_BIN" - "$raw" "$field" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
field = sys.argv[2]
value = payload.get(field)
if value in (None, "", [], {}):
    raise SystemExit(1)
raise SystemExit(0)
PY
}

post_json() {
  local url="$1"
  local data="$2"
  local response_file
  response_file="$(mktemp)"
  local http_code
  http_code="$(curl -sS -o "$response_file" -w '%{http_code}' "$url" \
    -H 'Content-Type: application/json' \
    -d "$data")"
  local body
  body="$(cat "$response_file")"
  rm -f "$response_file"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    echo "HTTP ${http_code} from ${url}" >&2
    if [[ -n "$body" ]]; then
      echo "$body" >&2
    fi
    return 1
  fi

  printf '%s' "$body"
}

trap 'echo; echo "冒烟测试失败。"; show_recent_logs' ERR

print_section "1. 健康检查"
ESM3_HEALTH="$(curl -fsS "${ESM3_URL}/health")"
AGENT_HEALTH="$(curl -fsS "${AGENT_URL}/health")"

echo "ESM3 服务: ${ESM3_URL}/health"
pretty_json "$ESM3_HEALTH"

echo
echo "Agent 服务: ${AGENT_URL}/health"
pretty_json "$AGENT_HEALTH"

print_section "2. 直接测试 ESM3 生成接口"
GENERATE_REQ="{\"prompt\":\"${SMOKE_SEQUENCE}\",\"num_candidates\":2,\"temperature\":0.8}"
GENERATE_RESP="$(post_json "${ESM3_URL}/generate_sequence" "$GENERATE_REQ")"
pretty_json "$GENERATE_RESP"
require_field "$GENERATE_RESP" "sequences"

print_section "3. 直接测试 ESM3 结构接口"
STRUCTURE_REQ="{\"sequence\":\"${SMOKE_SEQUENCE}\"}"
STRUCTURE_RESP="$(post_json "${ESM3_URL}/predict_structure" "$STRUCTURE_REQ")"
pretty_json "$STRUCTURE_RESP"
require_field "$STRUCTURE_RESP" "confidence"

print_section "4. 测试 Agent 最小 GFP 任务"
AGENT_REQ="{\"task\":\"${SMOKE_TASK}\",\"max_iterations\":${SMOKE_ITERATIONS},\"candidates_per_round\":${SMOKE_CANDIDATES}}"
AGENT_RESP="$(post_json "${AGENT_URL}/design_protein" "$AGENT_REQ")"
pretty_json "$AGENT_RESP"
require_field "$AGENT_RESP" "best_sequences"

print_section "5. 结果"
echo "冒烟测试通过：真实 ESM3 服务与 Agent 编排链路均正常。"
echo
echo "如需更深入检查，可继续执行："
echo "- ./status_all.sh"
echo "- tail -f ${ESM3_LOG}"
echo "- tail -f ${AGENT_LOG}"
