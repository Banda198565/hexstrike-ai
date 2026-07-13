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

mkdir -p "$ROOT/logs"

resolve_ollama_bin() {
  if command -v ollama >/dev/null 2>&1; then
    command -v ollama
    return 0
  fi
  for candidate in \
    "/opt/homebrew/bin/ollama" \
    "/usr/local/bin/ollama" \
    "$(brew --prefix ollama 2>/dev/null)/bin/ollama"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_ollama_cli() {
  if OLLAMA_BIN="$(resolve_ollama_bin)"; then
    export PATH="$(dirname "$OLLAMA_BIN"):$PATH"
    log "Ollama CLI: $OLLAMA_BIN"
    return 0
  fi
  log "Ollama CLI not in PATH — installing/linking..."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    command -v brew >/dev/null 2>&1 || die "Install Homebrew: https://brew.sh"
    if brew list ollama &>/dev/null; then
      brew link ollama 2>/dev/null || brew link --overwrite ollama 2>/dev/null || true
    else
      brew install ollama
    fi
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  OLLAMA_BIN="$(resolve_ollama_bin)" || die "ollama still not found after install — run: brew link ollama"
  export PATH="$(dirname "$OLLAMA_BIN"):$PATH"
  log "Ollama CLI: $OLLAMA_BIN"
}

wait_for_ollama() {
  local i
  for i in $(seq 1 30); do
    if curl -sf --max-time 2 "${HOST}/api/tags" >/dev/null 2>&1; then
      log "Ollama API ready (${HOST})"
      return 0
    fi
    sleep 1
  done
  return 1
}

start_ollama() {
  export OLLAMA_ORIGINS="*"
  launchctl setenv OLLAMA_ORIGINS "*" 2>/dev/null || true

  if wait_for_ollama; then
    return 0
  fi

  # Homebrew CLI install has no Ollama.app — use serve or brew services
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1 && brew services list 2>/dev/null | grep -q ollama; then
      log "Starting via brew services..."
      brew services start ollama 2>/dev/null || true
      if wait_for_ollama; then
        return 0
      fi
    fi
    if [[ -d "/Applications/Ollama.app" ]]; then
      log "Opening Ollama.app..."
      open -a Ollama 2>/dev/null || true
      if wait_for_ollama; then
        return 0
      fi
    else
      log "No Ollama.app (brew CLI only) — using: ollama serve"
    fi
  fi

  log "Starting: ollama serve (log: logs/ollama-serve.log)"
  if pgrep -x ollama >/dev/null 2>&1; then
    log "ollama process already running — waiting for API..."
  else
    nohup ollama serve >>"$ROOT/logs/ollama-serve.log" 2>&1 &
  fi
  wait_for_ollama || die "Ollama not responding — run manually: ollama serve"
}

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

# ── Install / link Ollama CLI ───────────────────────────────────
ensure_ollama_cli

# ── Start Ollama server ─────────────────────────────────────────
start_ollama

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
