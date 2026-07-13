#!/usr/bin/env bash
# setup-local-ollama-orchestrator.sh — ONE SHOT: Ollama + deepseek-r1 + HexStrike orchestrator
# Mac:  cd /Volumes/Eva/mufasaai-storage/hexstrike-ai && bash scripts/setup-local-ollama-orchestrator.sh
# Linux: cd /opt/hexstrike-ai && bash scripts/setup-local-ollama-orchestrator.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL="${LLM_MODEL:-deepseek-r1:1.5b}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
BASE="${HOST%/}/v1"
ENV_FILE="$ROOT/.env"

log() { echo "[ollama-setup] $*"; }
die() { echo "[ollama-setup] FAIL: $*" >&2; exit 1; }

# Portable .env writer (no macOS sed -i pain)
python3 - "$ENV_FILE" "$HOST" "$BASE" "$MODEL" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
host, base, model = sys.argv[2], sys.argv[3], sys.argv[4]
pairs = {
    "OLLAMA_HOST": host,
    "OLLAMA_ORIGINS": "*",
    "OLLAMA_BYPASS_TUNNEL": "true",
    "OLLAMA_PUBLIC_BASE_URL": base,
    "LLM_PROVIDER": "ollama-local",
    "LLM_BASE_URL": base,
    "LLM_MODEL": model,
    "CURSOR_INTEGRATION_MODE": "OFFLINE_PRIMARY",
    "OLLAMA_NUM_THREAD": "16",
    "OLLAMA_NUM_PREDICT": "256",
}
lines: list[str] = []
existing: dict[str, str] = {}
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
        else:
            lines.append(line)
merged = {**existing, **pairs}
out = []
seen = set()
for k, v in merged.items():
    out.append(f"{k}={v}")
    seen.add(k)
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"[ok] .env LLM keys → {env_path}")
PY

# ── Install Ollama if missing ───────────────────────────────────
if ! command -v ollama >/dev/null 2>&1; then
  log "Ollama not found — installing..."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install ollama
    else
      die "Install Homebrew first: https://brew.sh then re-run this script"
    fi
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi

# ── Start Ollama ────────────────────────────────────────────────
export OLLAMA_ORIGINS="*"
launchctl setenv OLLAMA_ORIGINS "*" 2>/dev/null || true

if [[ "$(uname -s)" == "Darwin" ]]; then
  open -a Ollama 2>/dev/null || true
fi

if ! curl -sf --max-time 3 "${HOST}/api/tags" >/dev/null 2>&1; then
  log "Starting ollama serve..."
  nohup ollama serve >> "$ROOT/logs/ollama-serve.log" 2>&1 &
  sleep 5
fi

curl -sf --max-time 10 "${HOST}/api/tags" >/dev/null \
  || die "Ollama not responding at ${HOST} — open Ollama.app manually"

# ── Pull model ──────────────────────────────────────────────────
if ! ollama list 2>/dev/null | grep -q 'deepseek-r1'; then
  log "Pulling ${MODEL} (first time may take a few minutes)..."
  ollama pull "$MODEL"
else
  log "Model deepseek-r1 already present"
fi

# ── Cursor / project integration ──────────────────────────────
log "Writing .cursor/settings.json (OFFLINE_PRIMARY)..."
bash "$ROOT/scripts/enable-system-integration-mode.sh"

# ── Orchestrator handshake ──────────────────────────────────────
log "Orchestrator LLM handshake..."
set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

if [[ -f "$ROOT/hexstrike_env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/hexstrike_env/bin/activate"
fi

python3 "$ROOT/hexstrike_orchestrator.py" llm-handshake || true

log "Verify script..."
bash "$ROOT/scripts/verify-ollama-handshake.sh" || true

echo ""
echo "════════════════════════════════════════════════════════"
echo " DONE — local DeepSeek + orchestrator"
echo " Ollama:    ${HOST}"
echo " Model:     ${MODEL}"
echo " Orchestrator: python3 hexstrike_orchestrator.py llm-handshake"
echo " Test chat: curl ${BASE}/chat/completions -d '{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"stream\":false}'"
echo " Cursor: switch to LOCAL mode, model ${MODEL}, API key: ollama"
echo "════════════════════════════════════════════════════════"
