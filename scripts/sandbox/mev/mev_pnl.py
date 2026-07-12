#!/usr/bin/env python3
"""Pure PnL / classifier math for MEV engines (unit-testable, no RPC)."""
from __future__ import annotations

from dataclasses import dataclass

FEE_BPS_DEFAULT = 30
PANCAKE_FEE_BPS = 25  # 0.25% V2
JIT_GAS_UNITS_DEFAULT = 450_000
JIT_GAS_PRICE_DEFAULT = 1_000_000_000


def cp_amount_out(amount_in: int, reserve_in: int, reserve_out: int) -> int:
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    return (amount_in * reserve_out) // (reserve_in + amount_in)


@dataclass
class JITClassifier:
    victim_swap_wei: int
    jit_liquidity: int
    total_liq_before: int
    fee_total_wei: int
    fee_share_wei: int
    gas_cost_wei: int
    il_estimate_wei: int
    net_wei: int
    profitable: bool
    should_execute: bool
    skip_reason: str | None = None


def estimate_jit_il_wei(
    victim_swap_wei: int,
    pool_eth_wei: int,
    pool_token_units: int,
    jit_eth_wei: int,
    jit_liquidity: int,
) -> int:
    """Impermanent-loss proxy: JIT LP value drift after victim moves the curve."""
    if pool_eth_wei <= 0 or pool_token_units <= 0 or jit_eth_wei <= 0:
        return 0
    eth_before = jit_eth_wei
    tok_before = jit_liquidity
    # Victim swap shifts pool
    fee = victim_swap_wei * FEE_BPS_DEFAULT // 10_000
    net_v = victim_swap_wei - fee
    out_v = cp_amount_out(net_v, pool_eth_wei, pool_token_units)
    eth2 = pool_eth_wei + net_v
    tok2 = pool_token_units - out_v
    # JIT share of pool after victim
    jit_eth_share = (eth2 * jit_eth_wei) // max(pool_eth_wei + jit_eth_wei, 1)
    jit_tok_share = (tok2 * jit_liquidity) // max(pool_token_units + jit_liquidity, 1)
    # Mark-to-market in ETH at post-victim marginal price
    if jit_tok_share <= 0:
        return max(0, eth_before - jit_eth_share)
    marginal = (eth2 * 1_000_000) // max(tok2, 1)
    mtm_wei = jit_eth_share + (jit_tok_share * marginal) // 1_000_000
    return max(0, eth_before - mtm_wei)


def classify_jit(
    victim_swap_wei: int,
    jit_liquidity: int,
    total_liq_before: int,
    *,
    pool_eth_wei: int = 0,
    pool_token_units: int = 0,
    jit_eth_wei: int = 0,
    gas_units: int = JIT_GAS_UNITS_DEFAULT,
    gas_price_wei: int = JIT_GAS_PRICE_DEFAULT,
    fee_bps: int = FEE_BPS_DEFAULT,
) -> JITClassifier:
    fee_total = victim_swap_wei * fee_bps // 10_000
    denom = max(total_liq_before + jit_liquidity, 1)
    fee_share = fee_total * jit_liquidity // denom
    gas_cost = gas_units * gas_price_wei
    il_wei = 0
    if pool_eth_wei > 0 and pool_token_units > 0 and jit_eth_wei > 0:
        il_wei = estimate_jit_il_wei(
            victim_swap_wei, pool_eth_wei, pool_token_units, jit_eth_wei, jit_liquidity
        )
        # High slippage proxy when victim dwarfs pool depth
        if victim_swap_wei > pool_eth_wei:
            impact_bps = min(10_000, (victim_swap_wei * 10_000) // max(pool_eth_wei, 1))
            proxy_il = jit_eth_wei * impact_bps // 10_000
            il_wei = max(il_wei, proxy_il)
    net = fee_share - gas_cost - il_wei
    profitable = net > 0
    skip_reason = None
    if gas_cost >= fee_share:
        skip_reason = "gas_exceeds_fee_share"
    elif il_wei >= fee_share:
        skip_reason = "il_exceeds_fee_share"
    elif net <= 0:
        skip_reason = "net_non_positive"
    return JITClassifier(
        victim_swap_wei=victim_swap_wei,
        jit_liquidity=jit_liquidity,
        total_liq_before=total_liq_before,
        fee_total_wei=fee_total,
        fee_share_wei=fee_share,
        gas_cost_wei=gas_cost,
        il_estimate_wei=il_wei,
        net_wei=net,
        profitable=profitable,
        should_execute=profitable,
        skip_reason=skip_reason,
    )


@dataclass
class ForkSandwichSim:
    reserves_eth: int
    reserves_token: int
    victim_bnb_wei: int
    frontrun_bnb_wei: int
    estimated_profit_wei: int
    network_fee_wei: int
    net_profit_wei: int
    profitable: bool
    should_execute: bool
    skip_reason: str | None = None


def sandwich_pnl_from_reserves(
    reserve_eth: int,
    reserve_token: int,
    victim_bnb_wei: int,
    frontrun_bnb_wei: int,
    *,
    swap_fee_bps: int = PANCAKE_FEE_BPS,
    network_fee_wei: int = 210_000 * 3_000_000_000,  # ~3 txs at 3 gwei
) -> ForkSandwichSim:
    eth_res, tok_res = reserve_eth, reserve_token

    def swap_in(amount: int, rin: int, rout: int) -> tuple[int, int, int]:
        fee = amount * swap_fee_bps // 10_000
        net = amount - fee
        out = cp_amount_out(net, rin, rout)
        return out, rin + net, rout - out

    fr_out, eth_res, tok_res = swap_in(frontrun_bnb_wei, eth_res, tok_res)
    _, eth_res, tok_res = swap_in(victim_bnb_wei, eth_res, tok_res)
    eth_back = cp_amount_out(fr_out, tok_res, eth_res)
    gross = eth_back - frontrun_bnb_wei
    net = gross - network_fee_wei
    profitable = net > 0
    skip = None
    if gross <= 0:
        skip = "zero_or_negative_gross_spread"
    elif net <= 0:
        skip = "network_fees_exceed_gross"
    return ForkSandwichSim(
        reserves_eth=eth_res,
        reserves_token=tok_res,
        victim_bnb_wei=victim_bnb_wei,
        frontrun_bnb_wei=frontrun_bnb_wei,
        estimated_profit_wei=gross,
        network_fee_wei=network_fee_wei,
        net_profit_wei=net,
        profitable=profitable,
        should_execute=profitable,
        skip_reason=skip,
    )


@dataclass
class BackrunClassifier:
    arb_eth_wei: int
    bridge_fee_wei: int
    pool_a_out_wei: int
    pool_b_out_wei: int
    gross_profit_wei: int
    net_profit_wei: int
    profitable: bool
    should_execute: bool
    skip_reason: str | None = None


def classify_backrun(
    arb_eth_wei: int,
    pool_a_out_wei: int,
    pool_b_out_wei: int,
    *,
    bridge_fee_wei: int = 0,
) -> BackrunClassifier:
    gross = pool_a_out_wei - arb_eth_wei
    net = gross - bridge_fee_wei
    profitable = net > 0 and pool_b_out_wei > pool_a_out_wei
    skip = None
    if pool_b_out_wei <= pool_a_out_wei:
        skip = "no_cross_pool_spread"
    elif bridge_fee_wei >= gross:
        skip = "bridge_fee_kills_profit"
    elif net <= 0:
        skip = "net_non_positive"
    return BackrunClassifier(
        arb_eth_wei=arb_eth_wei,
        bridge_fee_wei=bridge_fee_wei,
        pool_a_out_wei=pool_a_out_wei,
        pool_b_out_wei=pool_b_out_wei,
        gross_profit_wei=gross,
        net_profit_wei=net,
        profitable=profitable,
        should_execute=profitable,
        skip_reason=skip,
    )
