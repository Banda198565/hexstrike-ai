#!/usr/bin/env bash
# mac-local-model-only.sh — ТОЛЬКО локальная deepseek-r1:1.5b на iMac (без VPS, без tunnel, без Cloud)
set -euo pipefail

ROOT="${HEXSTRIKE_ROOT:-${HOME}/hexstrike-ai}"
MODEL="${HEXSTRIKE_MODEL:-deepseek-r1:1.5b}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
BASE="${HOST%/}/v1"

log() { echo "[local-model] $*"; }
die() { echo "[local-model] ERROR: $*" >&2; exit 1; }

[[ -d "$ROOT" ]] || die "Нет репо: $ROOT"

cd "$ROOT"
git fetch origin cursor/architecture-manifest-c48c 2>/dev/null || true
git pull origin cursor/architecture-manifest-c48c 2>/dev/null || true

export OLLAMA_ORIGINS="*"
if [[ "$(uname -s)" == "Darwin" ]]; then
  launchctl setenv OLLAMA_ORIGINS "*" 2>/dev/null || true
  open -a Ollama 2>/dev/null || true
fi

log "1/4 Ollama..."
for _ in $(seq 1 20); do
  curl -sf --max-time 3 "${HOST}/api/tags" >/dev/null && break
  sleep 1
done
curl -sf --max-time 5 "${HOST}/api/tags" >/dev/null || die "Ollama не отвечает. Открой Ollama.app"

log "2/4 Модель ${MODEL}..."
ollama pull "${MODEL}"

log "3/4 OFFLINE_PRIMARY (localhost, без tunnel)..."
export OLLAMA_MODEL="$MODEL"
"$ROOT/scripts/enable-system-integration-mode.sh"

log "4/4 Тест chat..."
REPLY=$(curl -sf --max-time 90 "${BASE}/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"options\":{\"num_predict\":32},\"messages\":[{\"role\":\"user\",\"content\":\"Say: OK\"}]}")
echo "$REPLY" | python3 -c "import json,sys; d=json.load(sys.stdin); print('  →', (d.get('choices',[{}])[0].get('message',{}).get('content') or d.get('error','?'))[:80])"

echo ""
echo "=========================================="
echo "  ЛОКАЛЬНАЯ МОДЕЛЬ ГОТОВА"
echo "=========================================="
echo ""
echo "  Cursor → Settings → Models:"
echo "    Override Base URL:  ${BASE}"
echo "    API Key:            ollama"
echo "    Model:              ${MODEL}"
echo "    → Verify (зелёная галочка)"
echo ""
echo "  Composer → выбери ${MODEL}"
echo "  Режим: Desktop Cursor (не Cloud Agent)"
echo ""
echo "  Проверка: ./scripts/verify-ollama-handshake.sh"
echo "  Доложение: ./scripts/generate-model-report.sh http://127.0.0.1:8888"
echo "             (если orchestrator на VPS — сначала mac-local-report.sh)"
echo ""
