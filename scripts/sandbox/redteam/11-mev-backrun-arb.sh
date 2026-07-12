#!/usr/bin/env bash
# 11-mev-backrun-arb.sh — backrun cross-pool arbitrage (Anvil only)
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 11: MEV backrun arbitrage ==="

CHAIN="$(cast chain-id --rpc-url "$RPC")"
if [[ "$CHAIN" != "31337" ]]; then
  log_result "11-mev-backrun-arb" "INCONCLUSIVE" "refuse non-Anvil chain_id=$CHAIN"
  exit 0
fi

export MEV_RPC_URL="$RPC" MEV_SANDBOX_ONLY=1

if python3 "$SANDBOX/mev/backrun_engine.py" > /tmp/mev-11.log 2>&1; then
  profit="$(python3 -c "import json;print(json.load(open('$ROOT/artifacts/sandbox/mev-backrun-result.json'))['profit_wei'])")"
  log_result "11-mev-backrun-arb" "VULN_CONFIRMED" "backrun profit=${profit} wei"
else
  log_result "11-mev-backrun-arb" "INCONCLUSIVE" "backrun_engine failed — /tmp/mev-11.log"
fi
