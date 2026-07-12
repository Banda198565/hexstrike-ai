#!/usr/bin/env bash
# 10-mev-jit-liquidity.sh — JIT liquidity offensive (MockCLAMM, Anvil only)
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 10: MEV JIT liquidity ==="

CHAIN="$(cast chain-id --rpc-url "$RPC")"
if [[ "$CHAIN" != "$REDTEAM_CHAIN_ID" ]]; then
  log_result "10-mev-jit-liquidity" "INCONCLUSIVE" "refuse chain_id=$CHAIN want=$REDTEAM_CHAIN_ID"
  exit 0
fi

export MEV_RPC_URL="$RPC" MEV_SANDBOX_ONLY=1 MEV_ALLOWED_CHAINS="${MEV_ALLOWED_CHAINS:-$REDTEAM_CHAIN_ID}" JIT_FORCE_DEMO=1

if python3 "$SANDBOX/mev/jit_engine.py" > /tmp/mev-10.log 2>&1; then
  profit="$(python3 -c "import json;print(json.load(open('$ROOT/artifacts/sandbox/mev-jit-result.json'))['net_after_gas_wei'])")"
  log_result "10-mev-jit-liquidity" "VULN_CONFIRMED" "JIT net profit=${profit} wei after gas"
else
  log_result "10-mev-jit-liquidity" "INCONCLUSIVE" "jit_engine failed — /tmp/mev-10.log"
fi
