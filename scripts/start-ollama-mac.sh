#!/usr/bin/env bash
# start-ollama-mac.sh — brew CLI only (no Ollama.app required)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
export OLLAMA_ORIGINS="*"
command -v ollama >/dev/null 2>&1 || { echo "run: brew link ollama"; exit 1; }
if curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "[ok] Ollama already up"
  exit 0
fi
brew services start ollama 2>/dev/null || true
sleep 3
if curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "[ok] Ollama via brew services"
  exit 0
fi
nohup ollama serve >>"$ROOT/logs/ollama-serve.log" 2>&1 &
for i in $(seq 1 20); do
  curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null && { echo "[ok] ollama serve pid $(pgrep -x ollama)"; exit 0; }
  sleep 1
done
echo "[fail] tail -20 $ROOT/logs/ollama-serve.log"
tail -20 "$ROOT/logs/ollama-serve.log" 2>/dev/null || true
exit 1
