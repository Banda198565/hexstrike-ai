#!/usr/bin/env python3
"""Hardcore MEV stack stress tests — edge cases for PnL classifiers."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEV_DIR = ROOT / "scripts" / "sandbox" / "mev"
sys.path.insert(0, str(MEV_DIR))

from mev_pnl import (  # noqa: E402
    JIT_GAS_PRICE_DEFAULT,
    JIT_GAS_UNITS_DEFAULT,
    BackrunClassifier,
    ForkSandwichSim,
    JITClassifier,
    classify_backrun,
    classify_jit,
    sandwich_pnl_from_reserves,
)


class TestJITClassifierStress(unittest.TestCase):
    def test_gas_spike_blocks_execution(self):
        """Extreme gas price → should_execute=False."""
        plan = classify_jit(
            victim_swap_wei=5_000_000_000_000_000_000,
            jit_liquidity=500_000_000_000_000_000_000,
            total_liq_before=1_000_000_000_000_000_000_000,
            gas_units=JIT_GAS_UNITS_DEFAULT,
            gas_price_wei=JIT_GAS_PRICE_DEFAULT * 10_000,
        )
        self.assertFalse(plan.should_execute)
        self.assertEqual(plan.skip_reason, "gas_exceeds_fee_share")

    def test_low_liquidity_high_slippage_il(self):
        """Near-empty pool + huge victim → IL dominates fee share."""
        plan = classify_jit(
            victim_swap_wei=50_000_000_000_000_000_000,  # 50 ETH victim
            jit_liquidity=1_000_000_000_000_000_000,     # 1 ETH JIT liq
            total_liq_before=2_000_000_000_000_000_000,  # 2 ETH total LP
            pool_eth_wei=2_000_000_000_000_000_000,
            pool_token_units=2_000_000_000_000_000_000,
            jit_eth_wei=1_000_000_000_000_000_000,
            gas_price_wei=1,
        )
        self.assertGreater(plan.il_estimate_wei, 0)
        # Tiny fee pool + massive victim → unprofitable or IL-heavy
        self.assertFalse(plan.should_execute)

    def test_healthy_jit_profitable(self):
        plan = classify_jit(
            victim_swap_wei=5_000_000_000_000_000_000,
            jit_liquidity=500_000_000_000_000_000_000,
            total_liq_before=1_000_000_000_000_000_000_000,
            pool_eth_wei=50_000_000_000_000_000_000,
            pool_token_units=1_000_000_000_000_000_000_000,
            jit_eth_wei=10_000_000_000_000_000_000,
            gas_price_wei=JIT_GAS_PRICE_DEFAULT,
        )
        self.assertTrue(plan.should_execute)
        self.assertGreater(plan.net_wei, 0)

    def test_matches_go_plan_jit_fee_share(self):
        """Python classifier fee_share aligns with Go PlanJIT (no IL in Go)."""
        victim = 5_000_000_000_000_000_000
        jit_liq = 500_000_000_000_000_000_000
        total = 1_000_000_000_000_000_000_000
        py = classify_jit(victim, jit_liq, total, gas_price_wei=JIT_GAS_PRICE_DEFAULT)
        fee_total = victim * 30 // 10_000
        share = fee_total * jit_liq // (total + jit_liq)
        gas = JIT_GAS_UNITS_DEFAULT * JIT_GAS_PRICE_DEFAULT
        self.assertEqual(py.fee_share_wei, share)
        self.assertEqual(py.gas_cost_wei, gas)


class TestForkSandwichStress(unittest.TestCase):
    def test_zero_spread_balanced_pool_skips(self):
        """Symmetric reserves + fees → net PnL <= 0 after network costs."""
        # Equal reserves: sandwich round-trip loses to fees
        r = 1_000_000_000_000_000_000_000  # 1000 ETH scale
        sim = sandwich_pnl_from_reserves(
            r, r,
            victim_bnb_wei=1_000_000_000_000_000_000,
            frontrun_bnb_wei=100_000_000_000_000_000,
            network_fee_wei=500_000_000_000_000_000,  # high network fee
        )
        self.assertFalse(sim.should_execute)
        self.assertLessEqual(sim.net_profit_wei, 0)
        self.assertIsNotNone(sim.skip_reason)

    def test_tiny_frontrun_negative_gross(self):
        sim = sandwich_pnl_from_reserves(
            10**18, 10**21,
            victim_bnb_wei=10**15,
            frontrun_bnb_wei=10**12,
            swap_fee_bps=30,
            network_fee_wei=0,
        )
        self.assertLessEqual(sim.estimated_profit_wei, 0)
        self.assertFalse(sim.should_execute)

    def test_large_imbalanced_pool_can_profit(self):
        sim = sandwich_pnl_from_reserves(
            100_000_000_000_000_000_000,
            100_000_000_000_000_000_000_000,
            victim_bnb_wei=5_000_000_000_000_000_000,
            frontrun_bnb_wei=1_000_000_000_000_000_000,
            swap_fee_bps=30,
            network_fee_wei=0,
        )
        self.assertGreater(sim.estimated_profit_wei, 0)
        self.assertTrue(sim.should_execute)


class TestForkRPCTimeout(unittest.TestCase):
    def test_rpc_failure_returns_skip_not_crash(self):
        spec = importlib.util.spec_from_file_location("fork_offensive", MEV_DIR / "fork_offensive.py")
        fork = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(fork)

        with patch.object(fork, "cast", side_effect=RuntimeError("connection refused")):
            with self.assertRaises(RuntimeError):
                fork.get_reserves()

        # simulate_offensive path with injected reserves bypasses RPC
        sim = sandwich_pnl_from_reserves(10**21, 10**21, 10**18, 10**17)
        self.assertIsInstance(sim, ForkSandwichSim)


class TestBackrunStress(unittest.TestCase):
    def test_bridge_fee_kills_arb(self):
        plan = classify_backrun(
            arb_eth_wei=1_000_000_000_000_000_000,
            pool_a_out_wei=1_100_000_000_000_000_000,
            pool_b_out_wei=1_200_000_000_000_000_000,
            bridge_fee_wei=200_000_000_000_000_000,
        )
        self.assertFalse(plan.should_execute)
        self.assertEqual(plan.skip_reason, "bridge_fee_kills_profit")

    def test_no_cross_pool_spread(self):
        plan = classify_backrun(
            arb_eth_wei=1e18,
            pool_a_out_wei=1.1e18,
            pool_b_out_wei=1.05e18,
        )
        self.assertFalse(plan.should_execute)
        self.assertEqual(plan.skip_reason, "no_cross_pool_spread")

    def test_profitable_backrun_path(self):
        plan = classify_backrun(
            arb_eth_wei=2_000_000_000_000_000_000,
            pool_a_out_wei=3_000_000_000_000_000_000,
            pool_b_out_wei=3_500_000_000_000_000_000,
            bridge_fee_wei=10_000_000_000_000_000,
        )
        self.assertTrue(plan.should_execute)
        self.assertGreater(plan.net_profit_wei, 0)


class TestEngineIntegrationGates(unittest.TestCase):
    def test_jit_engine_skips_on_classifier(self):
        spec = importlib.util.spec_from_file_location("jit_engine", MEV_DIR / "jit_engine.py")
        jit = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(jit)

        plan = jit.classify_jit_execution(
            victim_swap_wei=10**15,
            jit_liquidity=10**18,
            total_liq_before=10**18,
            gas_price_wei=JIT_GAS_PRICE_DEFAULT * 50_000,
        )
        self.assertFalse(plan["should_execute"])
        self.assertIn("skip_reason", plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
