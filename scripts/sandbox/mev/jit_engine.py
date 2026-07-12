#!/usr/bin/env python3
"""JIT liquidity offensive engine — Anvil sandbox ONLY."""
from __future__ import annotations

import os
import sys
import time

from mev_common import cast, forge_create, fund_defaults, parse_uint, require_anvil, wallet, write_artifact

# Offensive profit model defaults
FEE_BPS = 30
GAS_UNITS_JIT = int(os.environ.get("JIT_GAS_UNITS", "450000"))
GAS_PRICE_WEI = int(os.environ.get("JIT_GAS_PRICE_WEI", "1_000_000_000").replace("_", ""))


def estimate_jit_profitable(victim_swap_wei: int, jit_liquidity: int, total_liq_before: int) -> dict:
    """Classifier: fee share vs estimated gas (matches Go PlanJIT)."""
    fee = victim_swap_wei * FEE_BPS // 10_000
    share = fee * jit_liquidity // max(total_liq_before + jit_liquidity, 1)
    gas_cost = GAS_UNITS_JIT * GAS_PRICE_WEI
    return {
        "victim_swap_wei": victim_swap_wei,
        "fee_total_wei": fee,
        "jit_fee_share_wei": share,
        "gas_cost_wei": gas_cost,
        "profitable": share > gas_cost,
        "net_wei": share - gas_cost,
    }


def run_jit() -> dict:
    fund_defaults()
    attacker, attacker_key = wallet(2)
    victim, victim_key = wallet(3)

    # Seed pool with passive LP (index 4)
    passive, passive_key = wallet(4)
    pool = forge_create("MockCLAMM", value="50ether")

    # Passive baseline liquidity
    cast("send", pool, "addLiquidityJIT(uint128)", "1000000000000000000000",
         "--value", "40ether", "--private-key", passive_key)

    victim_swap = int(5e18)  # 5 ETH victim trade
    jit_liq = int(500e18)    # narrow JIT position
    model = estimate_jit_profitable(victim_swap, jit_liq, int(1000e18))
    if not model["profitable"]:
        model["note"] = "classifier says skip — increasing victim size for demo"
        victim_swap = int(20e18)
        model = estimate_jit_profitable(victim_swap, jit_liq, int(1000e18))

    attacker_eth_before = parse_uint(cast("balance", attacker))

    # JIT 1: add liquidity one block
    cast("send", pool, "addLiquidityJIT(uint128)", str(jit_liq),
         "--value", "10ether", "--private-key", attacker_key)

    # Victim swap — JIT LP captures fee share
    cast("send", pool, "swapETHForToken(uint256)", "0",
         "--value", str(victim_swap), "--private-key", victim_key)

    # JIT 3: remove + collect
    cast("send", pool, "removeLiquidityJIT(uint128)", str(jit_liq), "--private-key", attacker_key)

    attacker_eth_after = parse_uint(cast("balance", attacker))
    profit = attacker_eth_after - attacker_eth_before
    gas_cost = GAS_UNITS_JIT * GAS_PRICE_WEI

    return {
        "pool": pool,
        "attacker": attacker,
        "victim": victim,
        "victim_swap_wei": victim_swap,
        "classifier": model,
        "profit_wei": profit,
        "gas_cost_wei": gas_cost,
        "net_after_gas_wei": profit - gas_cost,
        "success": profit > 0 and (profit - gas_cost) > 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] JIT engine sandbox-only", file=sys.stderr)
        return 1
    if require_anvil() != "31337":
        print("[FAIL] JIT requires Anvil 31337", file=sys.stderr)
        return 1

    print("[jit] running JIT liquidity offensive...")
    result = run_jit()
    path = write_artifact("mev-jit-result.json", result)
    print(f"[jit] → {path}")
    print(__import__("json").dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
