#!/usr/bin/env bash
# fresh-start-mac.sh — ONE clean setup: Ollama + tunnel + Cursor (run on iMac)
set -euo pipefail

# Works when piped (curl | bash) or executed from repo
if [[ -n "${HEXSTRIKE_ROOT:-}" ]]; then
  ROOT="$(cd "$HEXSTRIKE_ROOT" && pwd)"
elif [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
elif [[ -d "${HOME}/hexstrike-ai" ]]; then
  ROOT="${HOME}/hexstrike-ai"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"

MODEL="${HEXSTRIKE_MODEL:-deepseek-r1:1.5b}"
HOST="http://127.0.0.1:11434"
LOG="/tmp/hexstrike-cloudflared.log"

echo ""
echo "=========================================="
echo "  HexStrike FRESH START (clean slate)"
echo "=========================================="
echo ""

# --- stop old tunnels (keep Ollama app) ---
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# --- Ollama ---
export OLLAMA_ORIGINS="*"
if [[ "$(uname -s)" == "Darwin" ]]; then
  launchctl setenv OLLAMA_ORIGINS "*" 2>/dev/null || true
fi

if ! command -v ollama &>/dev/null; then
  echo "[FAIL] Install: brew install ollama"
  exit 1
fi

open -a Ollama 2>/dev/null || ollama serve >/dev/null 2>&1 &
echo "[wait] Ollama starting (15s)..."
sleep 15

if ! curl -sf --max-time 5 "${HOST}/api/tags" >/dev/null; then
  echo "[FAIL] Ollama not responding. Open Ollama.app manually."
  exit 1
fi
echo "[OK]   Ollama running"

echo "[pull] ${MODEL}..."
ollama pull "${MODEL}"

# --- clean .env ---
cat > "$ROOT/.env" <<ENV
HEXSTRIKE_API_KEY=change-me-local
OLLAMA_HOST=${HOST}
OLLAMA_ORIGINS=*
LLM_MODEL=${MODEL}
LLM_PROVIDER=ollama-local
LLM_BASE_URL=${HOST}/v1
CURSOR_INTEGRATION_MODE=OFFLINE_PRIMARY
ENV
echo "[OK]   .env rewritten"

# --- clean cursor settings (minimal) ---
mkdir -p "$ROOT/.cursor"
cat > "$ROOT/.cursor/settings.json" <<JSON
{
  "systemIntegrationMode": "OFFLINE_PRIMARY",
  "ollama": {
    "host": "${HOST}",
    "model": "${MODEL}"
  },
  "cursor": {
    "openai": {
      "overrideBaseUrl": true,
      "baseUrl": "REPLACE_WITH_TUNNEL_URL/v1",
      "apiKey": "ollama"
    },
    "models": {
      "custom": [
        {
          "id": "${MODEL}",
          "name": "${MODEL}",
          "baseUrl": "REPLACE_WITH_TUNNEL_URL/v1"
        }
      ]
    }
  }
}
JSON
echo "[OK]   .cursor/settings.json reset"

# --- local test ---
echo ""
echo "[test] local chat..."
LOCAL_REPLY=$(curl -sf --max-time 60 "${HOST}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"options\":{\"num_predict\":32},\"messages\":[{\"role\":\"user\",\"content\":\"Say: OK\"}]}") \
  || { echo "[FAIL] local chat failed"; exit 1; }
echo "$LOCAL_REPLY" | jq -r '.choices[0].message.content // .error.message' | head -1
echo "[OK]   local inference works"

# --- tunnel (cloudflared retry + localtunnel fallback) ---
start_cloudflared() {
  : > "$LOG"
  cloudflared tunnel --url "${HOST}" --protocol http2 >>"$LOG" 2>&1 &
  CF_PID=$!
  TUNNEL=""
  for _ in $(seq 1 45); do
    if ! kill -0 "$CF_PID" 2>/dev/null; then
      return 1
    fi
    TUNNEL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
    [[ -n "$TUNNEL" ]] && return 0
    if grep -qE 'error code: 1101|failed to unmarshal quick Tunnel' "$LOG" 2>/dev/null; then
      kill "$CF_PID" 2>/dev/null || true
      return 1
    fi
    sleep 1
  done
  kill "$CF_PID" 2>/dev/null || true
  return 1
}

start_localtunnel() {
  command -v npx >/dev/null || return 1
  LT_LOG="/tmp/hexstrike-localtunnel.log"
  : > "$LT_LOG"
  npx --yes localtunnel --port 11434 >>"$LT_LOG" 2>&1 &
  LT_PID=$!
  TUNNEL=""
  for _ in $(seq 1 30); do
    TUNNEL=$(grep -oE 'https://[a-z0-9-]+\.loca\.lt' "$LT_LOG" | head -1 || true)
    [[ -n "$TUNNEL" ]] && { CF_PID=$LT_PID; LOG=$LT_LOG; return 0; }
    sleep 1
  done
  kill "$LT_PID" 2>/dev/null || true
  return 1
}

echo ""
echo "[tunnel] starting (cloudflared, up to 3 tries)..."
TUNNEL=""
for attempt in 1 2 3; do
  echo "  attempt ${attempt}/3..."
  if start_cloudflared; then
    break
  fi
  echo "  cloudflared failed (1101 = Cloudflare API glitch), retry in 5s..."
  sleep 5
done

if [[ -z "$TUNNEL" ]]; then
  echo "[WARN] cloudflared unavailable — trying localtunnel..."
  start_localtunnel || true
fi

if [[ -z "$TUNNEL" ]]; then
  echo ""
  echo "=========================================="
  echo "  LOCAL OK — TUNNEL FAILED (Cloudflare 1101)"
  echo "=========================================="
  echo ""
  echo "  Ollama + deepseek-r1:1.5b work locally."
  echo "  Cursor Agents need a public URL. Try manually:"
  echo ""
  echo "  Option A — retry cloudflared in separate terminal:"
  echo "    cloudflared tunnel --url http://127.0.0.1:11434 --protocol http2"
  echo ""
  echo "  Option B — ngrok:"
  echo "    brew install ngrok && ngrok http 11434"
  echo ""
  echo "  Option C — localtunnel:"
  echo "    npx localtunnel --port 11434"
  echo ""
  echo "  Then Cursor Settings → Base URL: https://YOUR-URL/v1"
  echo "  Model: ${MODEL} | API Key: ollama"
  echo ""
  tail -5 "$LOG" 2>/dev/null || true
  exit 0
fi

BASE="${TUNNEL}/v1"
echo "[OK]   tunnel: ${TUNNEL}"

sleep 3
TUN_REPLY=$(curl -sf --max-time 30 "${BASE}/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"options\":{\"num_predict\":16},\"messages\":[{\"role\":\"user\",\"content\":\"Say: OK\"}]}") \
  || { echo "[FAIL] tunnel chat failed — check cloudflared log"; tail -10 "$LOG"; exit 1; }
echo "[OK]   tunnel chat: $(echo "$TUN_REPLY" | jq -r '.choices[0].message.content' | head -c 60)"

# patch settings with real tunnel
python3 - "$ROOT/.cursor/settings.json" "$BASE" "$MODEL" <<'PY'
import json, sys
p, base, model = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.loads(open(p).read())
d["cursor"]["openai"]["baseUrl"] = base
d["cursor"]["models"]["custom"][0]["baseUrl"] = base
open(p, "w").write(json.dumps(d, indent=2) + "\n")
PY

echo ""
echo "=========================================="
echo "  CURSOR SETTINGS (copy exactly)"
echo "=========================================="
echo ""
echo "  Settings → Models → OpenAI:"
echo "    Override Base URL: ${BASE}"
echo "    API Key:           ollama"
echo "    Model name:        ${MODEL}"
echo "    → Verify (green checkmark)"
echo ""
echo "  Composer dropdown → ${MODEL}"
echo "  Send: привет"
echo ""
echo "  Tunnel PID: ${CF_PID} (do NOT kill; log: ${LOG})"
echo "  To stop tunnel later: kill ${CF_PID}"
echo ""
echo "=========================================="
echo "  DONE — local + tunnel OK"
echo "=========================================="
