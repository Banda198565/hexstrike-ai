#!/usr/bin/env python3
"""Backrun arbitrage offensive engine — multi-pool sandbox (Anvil only)."""
from __future__ import annotations

import json
import os
import sys
import time

from mev_common import cast, forge_create, fund_defaults, parse_uint, require_anvil, wallet, write_artifact
from mev_pnl import classify_backrun

BRIDGE_FEE_WEI = int(os.environ.get("BACKRUN_BRIDGE_FEE_WEI", "0"))


def classify_backrun_execution(
    arb_eth_wei: int,
    pool_a_out_wei: int,
    pool_b_out_wei: int,
    bridge_fee_wei: int = BRIDGE_FEE_WEI,
) -> dict:
    plan = classify_backrun(arb_eth_wei, pool_a_out_wei, pool_b_out_wei, bridge_fee_wei=bridge_fee_wei)
    return {
        "arb_eth_wei": plan.arb_eth_wei,
        "bridge_fee_wei": plan.bridge_fee_wei,
        "gross_profit_wei": plan.gross_profit_wei,
        "net_profit_wei": plan.net_profit_wei,
        "profitable": plan.profitable,
        "should_execute": plan.should_execute,
        "skip_reason": plan.skip_reason,
    }


def run_backrun() -> dict:
    fund_defaults()
    attacker, attacker_key = wallet(2)
    victim, victim_key = wallet(3)

    pool_a = forge_create("MockAMM", value="100ether")
    pool_b = forge_create("MockAMM", value="30ether")
    cast(
        "send",
        pool_b,
        "addLiquidity(uint256)",
        str(int(5000e18)),
        "--value",
        "5ether",
        "--private-key",
        wallet(0)[1],
    )
    router = forge_create("MockRouter", ctor_args=[pool_a, pool_b])

    victim_eth = int(os.environ.get("BACKRUN_VICTIM_WEI", str(int(15e18))))
    arb_eth = int(os.environ.get("BACKRUN_ARB_WEI", str(int(2e18))))
    bridge_fee = int(os.environ.get("BACKRUN_BRIDGE_FEE_WEI", "0"))

    victim_before = parse_uint(cast("balance", victim))
    cast(
        "send",
        pool_a,
        "swapETHForTokens(uint256)",
        "0",
        "--value",
        str(victim_eth),
        "--private-key",
        victim_key,
    )

    # Pre-flight gate when bridge fee models multi-pool dead-end
    if bridge_fee > 0:
        quote_b = parse_uint(cast("call", pool_b, "quoteETHForTokens(uint256)", str(arb_eth)))
        quote_a = parse_uint(
            cast("call", pool_a, "quoteETHForTokens(uint256)", str(arb_eth // 2))
        )
        model = classify_backrun_execution(arb_eth, quote_a, quote_b, bridge_fee)
        if not model["should_execute"]:
            return {
                "pool_a": pool_a,
                "pool_b": pool_b,
                "router": router,
                "classifier": model,
                "skipped": True,
                "skip_reason": model["skip_reason"],
                "success": False,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

    attacker_before = parse_uint(cast("balance", attacker))
    cast(
        "send",
        router,
        "backrunArb(uint256,uint256)",
        str(arb_eth),
        "0",
        "--value",
        str(arb_eth),
        "--private-key",
        attacker_key,
    )
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
        "skipped": False,
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
    if result.get("skipped"):
        return 0
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
