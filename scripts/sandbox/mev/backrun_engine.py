#!/usr/bin/env python3
"""Backrun arbitrage offensive engine — multi-pool sandbox (Anvil only)."""
from __future__ import annotations

import json
import os
import sys
import time

from mev_common import cast, forge_create, fund_defaults, parse_uint, require_anvil, wallet, write_artifact


def run_backrun() -> dict:
    fund_defaults()
    attacker, attacker_key = wallet(2)
    victim, victim_key = wallet(3)

    # Pool A: primary victim venue (shallower token side)
    pool_a = forge_create("MockAMM", value="100ether")
    # Pool B: deep token reserve — cheap ETH→token for attacker
    pool_b = forge_create("MockAMM", value="30ether")
    cast("send", pool_b, "addLiquidity(uint256)", str(int(5000e18)),
         "--value", "5ether", "--private-key", wallet(0)[1])

    router = forge_create("MockRouter", ctor_args=[pool_a, pool_b])

    victim_eth = int(15e18)  # large victim swap moves pool A curve
    victim_before = parse_uint(cast("balance", victim))

    cast("send", pool_a, "swapETHForTokens(uint256)", "0",
         "--value", str(victim_eth), "--private-key", victim_key)

    attacker_before = parse_uint(cast("balance", attacker))
    arb_eth = int(2e18)

    cast("send", router, "backrunArb(uint256,uint256)", str(arb_eth), "0",
         "--value", str(arb_eth), "--private-key", attacker_key)

    attacker_after = parse_uint(cast("balance", attacker))
    profit = attacker_after - attacker_before
    victim_after = parse_uint(cast("balance", victim))

    return {
        "pool_a": pool_a,
        "pool_b": pool_b,
        "router": router,
        "attacker": attacker,
        "victim": victim,
        "victim_swap_wei": victim_eth,
        "victim_spent_wei": victim_before - victim_after,
        "arb_eth_wei": arb_eth,
        "profit_wei": profit,
        "success": profit > 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] backrun sandbox-only", file=sys.stderr)
        return 1
    if require_anvil() != "31337":
        print("[FAIL] backrun requires Anvil 31337", file=sys.stderr)
        return 1

    print("[backrun] multi-pool arb after victim swap...")
    result = run_backrun()
    path = write_artifact("mev-backrun-result.json", result)
    print(f"[backrun] → {path}")
    print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
