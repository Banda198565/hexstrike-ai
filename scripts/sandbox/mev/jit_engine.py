#!/usr/bin/env python3
"""JIT liquidity offensive engine — Anvil sandbox ONLY."""
from __future__ import annotations

import os
import sys
import time

from mev_common import cast, forge_create, fund_defaults, parse_uint, require_anvil, wallet, write_artifact
from mev_pnl import JIT_GAS_PRICE_DEFAULT, JIT_GAS_UNITS_DEFAULT, classify_jit

FEE_BPS = 30


def classify_jit_execution(
    victim_swap_wei: int,
    jit_liquidity: int,
    total_liq_before: int,
    *,
    pool_eth_wei: int = 0,
    pool_token_units: int = 0,
    jit_eth_wei: int = 0,
    gas_units: int | None = None,
    gas_price_wei: int | None = None,
) -> dict:
    """Gate JIT mint/burn — returns should_execute + skip_reason."""
    plan = classify_jit(
        victim_swap_wei,
        jit_liquidity,
        total_liq_before,
        pool_eth_wei=pool_eth_wei,
        pool_token_units=pool_token_units,
        jit_eth_wei=jit_eth_wei,
        gas_units=gas_units or int(os.environ.get("JIT_GAS_UNITS", JIT_GAS_UNITS_DEFAULT)),
        gas_price_wei=gas_price_wei or int(
            os.environ.get("JIT_GAS_PRICE_WEI", str(JIT_GAS_PRICE_DEFAULT)).replace("_", "")
        ),
        fee_bps=FEE_BPS,
    )
    return {
        "victim_swap_wei": plan.victim_swap_wei,
        "jit_liquidity": plan.jit_liquidity,
        "fee_share_wei": plan.fee_share_wei,
        "gas_cost_wei": plan.gas_cost_wei,
        "il_estimate_wei": plan.il_estimate_wei,
        "net_wei": plan.net_wei,
        "profitable": plan.profitable,
        "should_execute": plan.should_execute,
        "skip_reason": plan.skip_reason,
    }


def run_jit() -> dict:
    fund_defaults()
    attacker, attacker_key = wallet(2)
    victim, victim_key = wallet(3)
    passive, passive_key = wallet(4)

    pool = forge_create("MockCLAMM", value="50ether")
    passive_liq = int(1000e18)
    passive_eth = int(40e18)
    cast(
        "send",
        pool,
        "addLiquidityJIT(uint128)",
        str(passive_liq),
        "--value",
        f"{passive_eth}",
        "--private-key",
        passive_key,
    )

    victim_swap = int(os.environ.get("JIT_VICTIM_WEI", str(int(5e18))))
    jit_liq = int(os.environ.get("JIT_LIQUIDITY", str(int(500e18))))
    jit_eth = int(os.environ.get("JIT_ETH_WEI", str(int(10e18))))

    model = classify_jit_execution(
        victim_swap,
        jit_liq,
        passive_liq,
        pool_eth_wei=passive_eth + int(50e18),
        pool_token_units=passive_liq,
        jit_eth_wei=jit_eth,
    )

    if not model["should_execute"] and os.environ.get("JIT_FORCE_DEMO") == "1":
        victim_swap = int(20e18)
        model = classify_jit_execution(
            victim_swap,
            jit_liq,
            passive_liq,
            pool_eth_wei=passive_eth + int(50e18),
            pool_token_units=passive_liq,
            jit_eth_wei=jit_eth,
        )
        model["force_demo"] = True

    if not model["should_execute"]:
        return {
            "pool": pool,
            "attacker": attacker,
            "victim": victim,
            "classifier": model,
            "skipped": True,
            "skip_reason": model["skip_reason"],
            "success": False,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    attacker_eth_before = parse_uint(cast("balance", attacker))
    cast(
        "send",
        pool,
        "addLiquidityJIT(uint128)",
        str(jit_liq),
        "--value",
        str(jit_eth),
        "--private-key",
        attacker_key,
    )
    cast(
        "send",
        pool,
        "swapETHForToken(uint256)",
        "0",
        "--value",
        str(victim_swap),
        "--private-key",
        victim_key,
    )
    cast("send", pool, "removeLiquidityJIT(uint128)", str(jit_liq), "--private-key", attacker_key)

    attacker_eth_after = parse_uint(cast("balance", attacker))
    profit = attacker_eth_after - attacker_eth_before
    gas_cost = model["gas_cost_wei"]

    return {
        "pool": pool,
        "attacker": attacker,
        "victim": victim,
        "victim_swap_wei": victim_swap,
        "classifier": model,
        "profit_wei": profit,
        "gas_cost_wei": gas_cost,
        "net_after_gas_wei": profit - gas_cost,
        "skipped": False,
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
    if result.get("skipped"):
        return 0
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
