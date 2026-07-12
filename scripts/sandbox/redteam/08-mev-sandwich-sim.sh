#!/usr/bin/env bash
# 08-mev-sandwich-sim.sh — offensive sandwich on MockAMM (Anvil sandbox ONLY)
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 08: MEV sandwich simulation (MockAMM) ==="

CHAIN="$(cast chain-id --rpc-url "$RPC")"
if [[ "$CHAIN" != "$REDTEAM_CHAIN_ID" ]]; then
  log_result "08-mev-sandwich-sim" "INCONCLUSIVE" "refuse chain_id=$CHAIN want=$REDTEAM_CHAIN_ID"
  exit 0
fi

export MEV_RPC_URL="$RPC"
export MEV_SANDBOX_ONLY=1
export MEV_ALLOWED_CHAINS="${MEV_ALLOWED_CHAINS:-$REDTEAM_CHAIN_ID}"

if ! python3 "$SANDBOX/mev/sandwich_engine.py" > /tmp/mev-08.log 2>&1; then
  log_result "08-mev-sandwich-sim" "INCONCLUSIVE" "sandwich_engine failed — see /tmp/mev-08.log"
  exit 0
fi

profit="$(python3 - "$ROOT/artifacts/sandbox/mev-sandwich-result.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("profit_wei", 0))
PY
)"

if [[ "$profit" -gt 0 ]]; then
  log_result "08-mev-sandwich-sim" "VULN_CONFIRMED" "attacker profit=${profit} wei — sandwich extracted slippage"
else
  log_result "08-mev-sandwich-sim" "DEFENDED" "no attacker profit"
fi
