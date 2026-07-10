#!/usr/bin/env bash
# mac-local-report.sh — доложение через локальную deepseek-r1:1.5b (iMac)
# Orchestrator на VPS: поднимает SSH-туннель :8888 автоматически.
set -euo pipefail

ROOT="${HEXSTRIKE_ROOT:-${HOME}/hexstrike-ai}"
VPS_HOST="${HEXSTRIKE_VPS:-78.27.235.70}"
VPS_USER="${HEXSTRIKE_VPS_USER:-root}"
ORCH_PORT="${HEXSTRIKE_ORCH_PORT:-8888}"
LOCAL_ORCH="http://127.0.0.1:${ORCH_PORT}"
OLLAMA="${OLLAMA_HOST:-http://127.0.0.1:11434}"
MODEL="${LLM_MODEL:-deepseek-r1:1.5b}"
TUNNEL_PID=""

cleanup() {
  [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT

log() { echo "[mac-report] $*"; }
die() { echo "[mac-report] ERROR: $*" >&2; exit 1; }

[[ -d "$ROOT" ]] || die "Repo not found: $ROOT (clone to ~/hexstrike-ai first)"

cd "$ROOT"
git fetch origin cursor/architecture-manifest-c48c 2>/dev/null || true
git checkout cursor/architecture-manifest-c48c -- scripts/ 2>/dev/null || \
  git pull origin cursor/architecture-manifest-c48c 2>/dev/null || true
chmod +x scripts/*.sh 2>/dev/null || true

log "1/4 Local Ollama..."
curl -sf --max-time 5 "${OLLAMA}/api/tags" >/dev/null || die "Ollama not running. Run: open -a Ollama"
TAGS=$(curl -sf "${OLLAMA}/api/tags" | python3 -c "import json,sys; print(','.join(m['name'] for m in json.load(sys.stdin).get('models',[])))")
echo "  models: $TAGS"
echo "$TAGS" | grep -q "$MODEL" || log "  warn: $MODEL not in list — ollama pull $MODEL"

log "2/4 SSH tunnel → VPS orchestrator (${VPS_USER}@${VPS_HOST}:${ORCH_PORT})..."
if curl -sf --max-time 2 "${LOCAL_ORCH}/health" >/dev/null 2>&1; then
  log "  orchestrator already reachable at ${LOCAL_ORCH}"
else
  ssh -f -N -o ExitOnForwardFailure=yes -o ConnectTimeout=10 \
    -L "${ORCH_PORT}:127.0.0.1:${ORCH_PORT}" "${VPS_USER}@${VPS_HOST}" || \
    die "SSH tunnel failed. Check: ssh ${VPS_USER}@${VPS_HOST}"
  TUNNEL_PID=$(pgrep -f "ssh -f -N.*${ORCH_PORT}:127.0.0.1:${ORCH_PORT}.*${VPS_HOST}" | head -1 || true)
  for _ in $(seq 1 10); do
    curl -sf --max-time 2 "${LOCAL_ORCH}/health" >/dev/null && break
    sleep 1
  done
  curl -sf --max-time 3 "${LOCAL_ORCH}/health" >/dev/null || die "Orchestrator not reachable via tunnel"
fi
HEALTH=$(curl -sf "${LOCAL_ORCH}/health")
echo "  $(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"status={d.get('status')} v={d.get('version')} tools={d.get('total_tools_available')}/{d.get('total_tools_count')}\")")"

BUNDLE="${ROOT}/artifacts/tech-detect-vps.json"
mkdir -p "${ROOT}/artifacts"

log "3/4 Technology fingerprint..."
"$ROOT/scripts/vps-technology-detect.sh" "$LOCAL_ORCH" "$BUNDLE"

log "4/4 Model report (local ${MODEL})..."
OLLAMA_HOST="$OLLAMA" LLM_MODEL="$MODEL" \
  "$ROOT/scripts/generate-model-report.sh" "$LOCAL_ORCH" "$BUNDLE"

echo ""
echo "=========================================="
echo "  DONE — local model report"
echo "=========================================="
echo "  Markdown: ${ROOT}/artifacts/model-report-tech-detect.md"
echo "  JSON:     ${ROOT}/artifacts/model-report-tech-detect.json"
echo "  Bundle:   ${BUNDLE}"
echo ""
cat "${ROOT}/artifacts/model-report-tech-detect.md"
