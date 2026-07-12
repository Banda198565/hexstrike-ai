#!/bin/bash
# Read-only smoke test for blockchain MCP layer
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$ROOT/hexstrike-env/bin/python3}"
HOT="${HOT:-0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA}"
USDT="0x55d398326f99059fF775485246999027B3197955"

echo "=== MCP smoke test ==="
"$PY" - <<PY
import sys
sys.path.insert(0, "$ROOT/mcp")
from lib.evm_client import EvmClient, OFFICIAL_USDT_BSC

c = EvmClient()
assert int(c.rpc("eth_chainId", []), 16) == 56
meta = c.token_meta(OFFICIAL_USDT_BSC)
assert meta["symbol"] == "USDT"
bal = c.balance_of(OFFICIAL_USDT_BSC, "$HOT", 18)
assert bal > 0, "hot wallet USDT balance expected"
tx = c.get_token_transfers(OFFICIAL_USDT_BSC, "$HOT", "both", 5000, 100)
assert tx["count"] > 0, "expected recent USDT transfers"
pair = c.pancake_pair(OFFICIAL_USDT_BSC, "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
assert pair, "Pancake USDT/WBNB pair expected"
print("OK chain=56 USDT=", meta["symbol"], "hot_bal=", round(bal, 2), "txs=", tx["count"], "pair=", pair)
PY

for mod in evm_rpc_mcp block_explorer_mcp defi_dex_mcp mev_offensive_mcp; do
  "$PY" -c "import importlib.util; s=importlib.util.spec_from_file_location('$mod','$ROOT/mcp/$mod.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('$mod import OK')"
done

echo "=== MEV MCP tool smoke ==="
MEV_SANDBOX_ONLY=1 BUILDER_SIM_ONLY=1 "$PY" - <<PY
import sys, os
sys.path.insert(0, "$ROOT/mcp")
os.environ.setdefault("MEV_SANDBOX_ONLY", "1")
os.environ.setdefault("BUILDER_SIM_ONLY", "1")
import importlib.util
spec = importlib.util.spec_from_file_location("mev_offensive_mcp", "$ROOT/mcp/mev_offensive_mcp.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = mod.builder_sim_dry_run(gross_profit_wei=0, network_fee_wei=630000000000000)
assert out.get("would_submit") is False, "builder must never submit"
assert out.get("simulation_only") is True
print("OK builder_sim would_submit=false simulation_only=true")
PY

echo "All MCP smoke checks passed."
