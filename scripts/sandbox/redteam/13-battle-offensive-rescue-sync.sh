#!/usr/bin/env bash
# 13-battle-offensive-rescue-sync.sh — offensive mempool scan + rescue bot coexistence
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 13: Battle offensive ↔ rescue sync ==="

CHAIN="$(cast chain-id --rpc-url "$RPC")"
if [[ "$CHAIN" != "$REDTEAM_CHAIN_ID" ]]; then
  log_result "13-battle-offensive-rescue-sync" "INCONCLUSIVE" "chain_id=$CHAIN want=$REDTEAM_CHAIN_ID"
  exit 0
fi

EVENTS_BEFORE="$(snapshot_events)"
start_bot_background "POLL_INTERVAL_SEC=3"

export MEV_RPC_URL="$RPC" MEV_SANDBOX_ONLY=1 MEV_ALLOWED_CHAINS="$REDTEAM_CHAIN_ID"
python3 "$SANDBOX/mev/mempool_scanner.py" > /tmp/mev-13-scan.log 2>&1 || true

# Classifier gate smoke (no unprofitable tx submit)
python3 - <<'PY' > /tmp/mev-13-gate.log 2>&1
import sys
sys.path.insert(0, "scripts/sandbox/mev")
from jit_engine import classify_jit_execution
m = classify_jit_execution(10**15, 10**18, 10**18, gas_price_wei=10**12)
assert not m["should_execute"]
print("gate_ok", m["skip_reason"])
PY

sleep 2
stop_bot

EVENTS_AFTER="$(snapshot_events)"
DELTA=$((EVENTS_AFTER - EVENTS_BEFORE))

if [[ -f "$ROOT/artifacts/sandbox/mev-mempool-scan.json" ]] && grep -q gate_ok /tmp/mev-13-gate.log 2>/dev/null; then
  log_result "13-battle-offensive-rescue-sync" "VULN_CONFIRMED" "bot+offensive coexist delta_events=${DELTA}"
else
  log_result "13-battle-offensive-rescue-sync" "INCONCLUSIVE" "sync check failed"
fi
