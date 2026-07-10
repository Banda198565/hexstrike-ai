#!/usr/bin/env bash
# verify-ollama-handshake.sh — diagnostic for Cursor ↔ Ollama integration
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
OLLAMA_ORIGINS="${OLLAMA_ORIGINS:-*}"

echo "=== HexStrike Ollama Handshake Diagnostic ==="
echo "Time: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "OLLAMA_HOST: $OLLAMA_HOST"
echo "OLLAMA_ORIGINS: $OLLAMA_ORIGINS"
echo ""

FAIL=0

check() {
  local name="$1"
  local ok="$2"
  local detail="$3"
  if [[ "$ok" == "1" ]]; then
    echo "[OK]   $name — $detail"
  else
    echo "[FAIL] $name — $detail"
    FAIL=$((FAIL + 1))
  fi
}

# 1. TCP socket
HOST_PORT="${OLLAMA_HOST#http://}"
HOST_PORT="${HOST_PORT#https://}"
HOST="${HOST_PORT%%:*}"
PORT="${HOST_PORT##*:}"
[[ "$PORT" == "$HOST" ]] && PORT=11434

if timeout 3 bash -c "echo >/dev/tcp/$HOST/$PORT" 2>/dev/null; then
  check "tcp_socket" 1 "$HOST:$PORT reachable"
else
  check "tcp_socket" 0 "$HOST:$PORT connection refused or timeout — is 'ollama serve' running?"
fi

# 2. GET /api/tags
TAGS_RESP="$(curl -sf --max-time 5 "${OLLAMA_HOST}/api/tags" 2>&1)" && TAGS_OK=1 || TAGS_OK=0
if [[ "$TAGS_OK" == "1" ]]; then
  check "api_tags" 1 "GET /api/tags OK"
  if echo "$TAGS_RESP" | grep -qi "deepseek-r1"; then
    check "model_deepseek_r1" 1 "deepseek-r1 present in model list"
  else
    check "model_deepseek_r1" 0 "deepseek-r1 NOT found — run: ollama pull deepseek-r1"
    echo "       Available models:"
    echo "$TAGS_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print('       ', [m.get('name') for m in d.get('models',[])])" 2>/dev/null || true
  fi
else
  check "api_tags" 0 "GET /api/tags failed: $TAGS_RESP"
fi

# 3. OpenAI-compatible /v1/models
MODELS_RESP="$(curl -sf --max-time 5 "${OLLAMA_HOST}/v1/models" 2>&1)" && MODELS_OK=1 || MODELS_OK=0
if [[ "$MODELS_OK" == "1" ]]; then
  check "openai_v1_models" 1 "GET /v1/models OK (Cursor uses this schema)"
else
  check "openai_v1_models" 0 "GET /v1/models failed: $MODELS_RESP"
fi

# 4. Minimal chat completion (chain-of-thought probe)
CHAT_RESP="$(curl -sf --max-time 30 "${OLLAMA_HOST}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-r1","messages":[{"role":"user","content":"Reply with exactly: pong"}],"stream":false}' 2>&1)" && CHAT_OK=1 || CHAT_OK=0
if [[ "$CHAT_OK" == "1" ]]; then
  check "chat_completion" 1 "POST /v1/chat/completions OK"
  if echo "$CHAT_RESP" | grep -qi "think\|pong"; then
    check "reasoning_path" 1 "model responded (CoT/reasoning capable)"
  fi
else
  check "chat_completion" 0 "POST /v1/chat/completions failed: ${CHAT_RESP:0:200}"
fi

# 5. Cursor localhost warning
PUBLIC_URL="${OLLAMA_PUBLIC_BASE_URL:-}"
if [[ -z "$PUBLIC_URL" || "$PUBLIC_URL" == *"127.0.0.1"* || "$PUBLIC_URL" == *"localhost"* ]]; then
  echo ""
  echo "[WARN] Cursor cloud backend cannot reach localhost directly."
  echo "       Start a tunnel, then set OLLAMA_PUBLIC_BASE_URL in .env:"
  echo "       cloudflared tunnel --url http://127.0.0.1:11434 --http-host-header=\"localhost:11434\""
  echo "       Then in Cursor UI: Settings → Models → Override OpenAI Base URL → https://<tunnel>/v1"
fi

# 6. settings.json
if [[ -f "$ROOT/.cursor/settings.json" ]]; then
  check "cursor_settings" 1 ".cursor/settings.json present"
else
  check "cursor_settings" 0 ".cursor/settings.json missing"
fi

echo ""
echo "=== Summary: failures=$FAIL ==="
exit "$FAIL"
