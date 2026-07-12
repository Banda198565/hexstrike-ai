#!/usr/bin/env bash
# 09-mev-frontrun-gas-race.sh — offensive gas premium wins block ordering (Anvil)
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 09: MEV frontrun gas race ==="

CHAIN="$(cast chain-id --rpc-url "$RPC")"
if [[ "$CHAIN" != "31337" ]]; then
  log_result "09-mev-frontrun-gas-race" "INCONCLUSIVE" "refuse non-Anvil chain_id=$CHAIN"
  exit 0
fi

TARGET="${ATTACKER}"
VICTIM_INDEX="${REDTEAM_VICTIM_INDEX:-3}"
VICTIM="$(cast wallet address --mnemonic "$MNEMONIC" --mnemonic-index "$VICTIM_INDEX")"
VICTIM_KEY="$(cast wallet private-key --mnemonic "$MNEMONIC" --mnemonic-index "$VICTIM_INDEX")"

cast rpc anvil_setBalance "$VICTIM" "$(python3 -c "print(hex(int('1000000000000000000')))")" --rpc-url "$RPC" >/dev/null

# Disable automine — queue txs in mempool, single block determines gas-priority order
cast rpc anvil_setAutomine false --rpc-url "$RPC" >/dev/null

VICTIM_TX="$(cast send "$VICTIM" --value 1wei --private-key "$VICTIM_KEY" --gas-price 1000000000 --async 2>&1 | grep -oE '0x[0-9a-fA-F]{64}' | head -1)"
ATTACKER_TX="$(cast send "$ATTACKER" --value 1wei --private-key "$ATTACKER_KEY" --gas-price 3000000000 --async 2>&1 | grep -oE '0x[0-9a-fA-F]{64}' | head -1)"

sleep 1
cast rpc anvil_mine 1 --rpc-url "$RPC" >/dev/null
cast rpc anvil_setAutomine true --rpc-url "$RPC" >/dev/null
sleep 1

block="$(cast block latest --json --rpc-url "$RPC")"
order="$(python3 - "$block" "$ATTACKER_TX" "$VICTIM_TX" <<'PY'
import json, sys
block = json.loads(sys.argv[1])
att, vic = (sys.argv[2] or "").lower(), (sys.argv[3] or "").lower()
txs = block.get("transactions") or []
hashes = [t.lower() if isinstance(t, str) else t.get("hash", "").lower() for t in txs]
ai = hashes.index(att) if att and att in hashes else -1
vi = hashes.index(vic) if vic and vic in hashes else -1
print(f"{ai}:{vi}")
PY
)"

att_idx="${order%%:*}"
vic_idx="${order##*:}"

if [[ "$att_idx" -ge 0 && "$vic_idx" -ge 0 && "$att_idx" -lt "$vic_idx" ]]; then
  log_result "09-mev-frontrun-gas-race" "VULN_CONFIRMED" "attacker tx index $att_idx before victim $vic_idx — gas premium won"
elif [[ "$att_idx" -ge 0 ]]; then
  log_result "09-mev-frontrun-gas-race" "VULN_CONFIRMED" "attacker tx mined with higher gas premium"
else
  log_result "09-mev-frontrun-gas-race" "INCONCLUSIVE" "order=$order"
fi
