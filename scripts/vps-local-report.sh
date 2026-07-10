#!/usr/bin/env bash
# vps-local-report.sh — доложение на VPS: orchestrator + локальный Ollama 1.5b
set -euo pipefail

ROOT="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
ORCH="${1:-http://localhost:8888}"
OLLAMA="${OLLAMA_HOST:-http://127.0.0.1:11434}"
MODEL="${LLM_MODEL:-deepseek-r1:1.5b}"

log() { echo "[vps-report] $*"; }
die() { echo "[vps-report] ERROR: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root on VPS"
[[ -d "$ROOT" ]] || die "Missing $ROOT"

cd "$ROOT"
git fetch origin cursor/architecture-manifest-c48c 2>/dev/null || true
git checkout cursor/architecture-manifest-c48c -- scripts/ 2>/dev/null || true
chmod +x scripts/*.sh 2>/dev/null || true

"$ROOT/scripts/vps-restore-known-good.sh"

if ! curl -sf --max-time 3 "${OLLAMA}/api/tags" >/dev/null; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
  systemctl enable ollama 2>/dev/null || true
  systemctl start ollama 2>/dev/null || ollama serve >/dev/null 2>&1 &
  sleep 5
fi
ollama pull "$MODEL" 2>/dev/null || true

BUNDLE="${ROOT}/artifacts/tech-detect-vps.json"
mkdir -p "${ROOT}/artifacts"
"$ROOT/scripts/vps-technology-detect.sh" "$ORCH" "$BUNDLE"

OLLAMA_HOST="$OLLAMA" LLM_MODEL="$MODEL" \
  "$ROOT/scripts/generate-model-report.sh" "$ORCH" "$BUNDLE"

echo ""
cat "${ROOT}/artifacts/model-report-tech-detect.md"
