#!/usr/bin/env bash
# connect-llm-orchestrator.sh — wire a running local LLM into HexStrike orchestrator
#
# Auto-detects llama-server (:8080) or Ollama (:11434), writes .env, does handshake.
#
# Usage (Mac):
#   bash scripts/connect-llm-orchestrator.sh
#   bash scripts/connect-llm-orchestrator.sh --provider llama-server
#   bash scripts/connect-llm-orchestrator.sh --provider ollama-local
#   bash scripts/connect-llm-orchestrator.sh --base-url http://127.0.0.1:8080/v1 --model HauhauCS/Qwen3.5
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROVIDER=""
BASE_URL=""
MODEL=""
API_KEY="${LLM_API_KEY:-ollama}"
LLAMA_HOST="${LLAMA_SERVER_HOST:-http://127.0.0.1:8080}"
OLLAMA_HOST_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider|--provider=*) [[ "$1" == *=* ]] && PROVIDER="${1#*=}" || { PROVIDER="$2"; shift; }; shift ;;
    --base-url|--base-url=*) [[ "$1" == *=* ]] && BASE_URL="${1#*=}" || { BASE_URL="$2"; shift; }; shift ;;
    --model|--model=*) [[ "$1" == *=* ]] && MODEL="${1#*=}" || { MODEL="$2"; shift; }; shift ;;
    --api-key|--api-key=*) [[ "$1" == *=* ]] && API_KEY="${1#*=}" || { API_KEY="$2"; shift; }; shift ;;
    --llama-host|--llama-host=*) [[ "$1" == *=* ]] && LLAMA_HOST="${1#*=}" || { LLAMA_HOST="$2"; shift; }; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[llm-connect] $*"; }
die() { echo "[llm-connect] FAIL: $*" >&2; exit 1; }

# Detect running provider if none forced
detect_llama() {
  curl -sf --max-time 3 "${LLAMA_HOST}/v1/models" >/dev/null 2>&1
}
detect_ollama() {
  curl -sf --max-time 3 "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1
}

if [[ -z "$PROVIDER" && -z "$BASE_URL" ]]; then
  log "Auto-detect (llama-server > ollama)"
  if detect_llama; then
    PROVIDER="llama-server"
  elif detect_ollama; then
    PROVIDER="ollama-local"
  else
    die "no local LLM detected (llama-server:8080 / ollama:11434)"
  fi
fi

case "$PROVIDER" in
  llama-server|llama.cpp|openai-local)
    detect_llama || die "$PROVIDER selected but ${LLAMA_HOST}/v1/models unreachable"
    BASE_URL="${BASE_URL:-${LLAMA_HOST}/v1}"
    if [[ -z "$MODEL" ]]; then
      MODEL=$(curl -sf "${LLAMA_HOST}/v1/models" | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('data') or [{}])[0].get('id','local'))" 2>/dev/null || echo "local")
    fi
    ;;
  ollama-local|ollama)
    detect_ollama || die "$PROVIDER selected but ${OLLAMA_HOST_URL} unreachable"
    BASE_URL="${BASE_URL:-${OLLAMA_HOST_URL}/v1}"
    if [[ -z "$MODEL" ]]; then
      MODEL=$(curl -sf "${OLLAMA_HOST_URL}/api/tags" | python3 -c "import json,sys; d=json.load(sys.stdin); m=d.get('models',[]); print(m[0]['name'] if m else 'deepseek-r1:1.5b')" 2>/dev/null || echo "deepseek-r1:1.5b")
    fi
    ;;
  custom)
    [[ -n "$BASE_URL" ]] || die "--provider custom requires --base-url"
    [[ -n "$MODEL" ]] || die "--provider custom requires --model"
    ;;
  *)
    die "unknown provider: $PROVIDER"
    ;;
esac

log "provider=$PROVIDER  base_url=$BASE_URL  model=$MODEL"

# Update .env
python3 - "$ROOT/.env" "$PROVIDER" "$BASE_URL" "$MODEL" "$API_KEY" "$LLAMA_HOST" "$OLLAMA_HOST_URL" <<'PY'
import sys
from pathlib import Path

env_path, provider, base_url, model, api_key, llama_host, ollama_host = sys.argv[1:8]
p = Path(env_path)
pairs = {
    "LLM_PROVIDER": provider,
    "LLM_BASE_URL": base_url,
    "LLM_MODEL": model,
    "LLM_API_KEY": api_key,
    "LLAMA_SERVER_HOST": llama_host,
    "OLLAMA_HOST": ollama_host,
    "OLLAMA_BYPASS_TUNNEL": "true",
    "CURSOR_INTEGRATION_MODE": "OFFLINE_PRIMARY",
    "HEXSTRIKE_LLM_SYSTEM_PROMPT_FILE": "config/llm-system-prompt.md",
    "LLM_PROVIDER_PRIORITY": "llama-server,ollama-local",
}
existing = {}
other = []
if p.is_file():
    for line in p.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
        else:
            other.append(line)
merged = {**existing, **pairs}
out = [f"{k}={v}" for k, v in merged.items()]
p.write_text("\n".join(other + out) + "\n")
print(f"[ok] .env → {p}")
PY

# Handshake — chat completion via new base_url
log "Handshake chat completion..."
RESP=$(curl -sf --max-time 30 "${BASE_URL}/chat/completions" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${API_KEY}" \
  -d "$(python3 -c "
import json, os
sys_prompt = ''
p = 'config/llm-system-prompt.md'
if os.path.isfile(p):
    sys_prompt = open(p).read().strip()
print(json.dumps({
  'model': '${MODEL}',
  'messages': [
    {'role': 'system', 'content': sys_prompt[:2000]},
    {'role': 'user', 'content': 'ping — respond with one word: pong'}
  ],
  'stream': False,
  'max_tokens': 32,
}))
")" 2>&1 || true)

if echo "$RESP" | grep -q '"content"'; then
  log "✅ chat OK"
  echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  reply:', d.get('choices',[{}])[0].get('message',{}).get('content','')[:200])" 2>/dev/null || true
else
  log "⚠️  chat probe returned non-standard response:"
  echo "  $RESP" | head -c 400; echo
fi

# Orchestrator status
log "Orchestrator LLM status..."
if [[ -f "$ROOT/hexstrike_env/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/hexstrike_env/bin/activate"
fi
python3 -c "
import os, sys
sys.path.insert(0, 'src')
os.environ['LLM_PROVIDER']='$PROVIDER'
os.environ['LLM_BASE_URL']='$BASE_URL'
os.environ['LLM_MODEL']='$MODEL'
from hexstrike.llm.provider import LocalLlmProvider
import json
print(json.dumps(LocalLlmProvider().status(), indent=2))
"

echo ""
echo "════════════════════════════════════════════════════════"
echo " LLM connected to HexStrike orchestrator"
echo "════════════════════════════════════════════════════════"
echo "  provider: $PROVIDER"
echo "  base_url: $BASE_URL"
echo "  model:    $MODEL"
echo "  system_prompt: config/llm-system-prompt.md (defensive-only)"
echo ""
echo " Verify: bash scripts/verify-ollama-handshake.sh"
echo " Status: ./hexstrike fastmcp status"
echo "════════════════════════════════════════════════════════"
