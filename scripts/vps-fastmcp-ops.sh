#!/usr/bin/env bash
# vps-fastmcp-ops.sh — recurring Alma/Ubuntu VPS FastMCP ops (dry-run only)
#
# Usage:
#   bash scripts/vps-fastmcp-ops.sh
#   bash scripts/vps-fastmcp-ops.sh --full     # + combat verify + pipeline
#   bash scripts/vps-fastmcp-ops.sh --quick    # vault status + nonce + verify only
#
# Safe for cron/systemd on VPS. Refuses HEXSTRIKE_TX_LIVE=1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:---standard}"
TARGET="${TARGET_ADDRESS:-${TARGET_WALLET:-0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA}}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${ROOT}/tx_logs/ops"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/ops_${RUN_ID}.log"

log() { echo "[vps-ops] $*"; }
die() { echo "[vps-ops] FAIL: $*" >&2; exit 1; }

exec > >(tee -a "$LOG") 2>&1

if [[ "${HEXSTRIKE_TX_LIVE:-}" == "1" ]]; then
  die "HEXSTRIKE_TX_LIVE=1 forbidden on VPS ops — Mac only"
fi
unset HEXSTRIKE_TX_LIVE || true
export DRY_RUN=true

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

# Prefer venv if present
if [[ -f "${ROOT}/hexstrike_env/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "${ROOT}/hexstrike_env/bin/activate"
fi

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

echo "════════════════════════════════════════════════════════"
echo " VPS FastMCP ops ($MODE) — DRY-RUN"
echo " RUN: $RUN_ID  TARGET: $TARGET"
echo "════════════════════════════════════════════════════════"

case "$MODE" in
  --quick|-q)
    log "vault status"
    "$HEXSTRIKE" vault status || true
    log "nonce"
    "$HEXSTRIKE" tx nonce || true
    log "fastmcp_verify"
    bash "${ROOT}/scripts/fastmcp_verify.sh" --target "$TARGET" --run-dry-run
    ;;
  --full|-f)
    log "sync --mcp"
    "$HEXSTRIKE" sync --mcp || true
    log "verify-combat-integration"
    bash "${ROOT}/scripts/verify-combat-integration.sh" "$ROOT" || true
    log "fastmcp_verify --run-dry-run"
    bash "${ROOT}/scripts/fastmcp_verify.sh" --target "$TARGET" --run-dry-run || true
    log "pipeline transaction-discovery"
    bash "${ROOT}/scripts/pipeline_transaction_discovery.sh" || true
    log "monitor combat readiness (short)"
    MONITOR_READINESS_SAMPLE_SEC=5 MONITOR_HEARTBEAT_POLLS=3 \
      bash "${ROOT}/scripts/monitor-combat-readiness.sh" || true
    ;;
  --standard|*)
    log "vault status"
    "$HEXSTRIKE" vault status || true
    log "nonce"
    "$HEXSTRIKE" tx nonce || true
    log "fastmcp_verify --run-dry-run"
    bash "${ROOT}/scripts/fastmcp_verify.sh" --target "$TARGET" --run-dry-run || true
    log "pipeline (dry)"
    bash "${ROOT}/scripts/pipeline_transaction_discovery.sh" || true
    ;;
esac

# Summary pointer
LATEST="${ROOT}/tx_logs/latest/fastmcp_cycle.json"
SUMMARY="${LOG_DIR}/latest_ops_summary.json"
python3 - <<PY
import json
from pathlib import Path
from datetime import datetime, timezone

summary = {
    "run_id": "${RUN_ID}",
    "mode": "${MODE}",
    "target": "${TARGET}",
    "host_role": "vps-watch-dry-run",
    "live_forbidden": True,
    "log": "${LOG}",
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
cycle = Path("${LATEST}")
if cycle.is_file():
    try:
        d = json.loads(cycle.read_text())
        summary["dry_run_success"] = d.get("success")
        summary["gate_allowed"] = (d.get("gate") or {}).get("allowed")
        summary["sign_hash"] = (d.get("sign") or {}).get("hash")
        summary["sign_from"] = (d.get("sign") or {}).get("from")
    except Exception as exc:
        summary["cycle_error"] = str(exc)

Path("${SUMMARY}").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY

echo ""
echo "[DONE] ops log → $LOG"
echo "[DONE] summary → $SUMMARY"
echo "[NOTE] Live broadcast remains Mac-only"
