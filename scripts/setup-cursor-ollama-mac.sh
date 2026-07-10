#!/usr/bin/env bash
# setup-cursor-ollama-mac.sh — operator Mac: Ollama + Cursor deepseek-r1 integration
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/5] Setting OLLAMA_HOST in .env"
grep -q '^OLLAMA_HOST=' "$ROOT/.env" 2>/dev/null && \
  sed -i.bak 's|^OLLAMA_HOST=.*|OLLAMA_HOST=http://127.0.0.1:11434|' "$ROOT/.env" || \
  echo 'OLLAMA_HOST=http://127.0.0.1:11434' >> "$ROOT/.env"

if ! grep -q '^OLLAMA_ORIGINS=' "$ROOT/.env" 2>/dev/null; then
  echo 'OLLAMA_ORIGINS=*' >> "$ROOT/.env"
fi

export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_ORIGINS=*

echo "[2/5] Checking ollama CLI"
if ! command -v ollama &>/dev/null; then
  echo "Install: brew install ollama  OR  https://ollama.com/download"
  exit 1
fi

echo "[3/5] Pull deepseek-r1 if missing"
if ! ollama list 2>/dev/null | grep -q 'deepseek-r1'; then
  ollama pull deepseek-r1
fi

echo "[4/5] Ensure ollama serve is running"
if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/tags &>/dev/null; then
  echo "Start Ollama app or run: ollama serve"
  exit 1
fi

echo "[5/5] Handshake verification"
"$ROOT/scripts/verify-ollama-handshake.sh"

echo ""
echo "=== Cursor UI (required — cannot be fully automated from repo) ==="
echo "1. Cursor → Settings → Models → Add model: deepseek-r1"
echo "2. Enable 'Override OpenAI Base URL'"
echo "3. If using cloud Cursor: set base URL to your tunnel (https://xxx.trycloudflare.com/v1)"
echo "4. API Key: ollama (any non-empty placeholder)"
echo "5. Disable other cloud models; select deepseek-r1 for Chat + Composer"
echo ""
echo "Project config locked in: .cursor/settings.json"
