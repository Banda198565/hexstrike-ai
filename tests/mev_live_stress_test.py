#!/usr/bin/env python3
"""Offline tests for live mempool + builder sim (production-hardening)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEV_DIR = ROOT / "scripts" / "sandbox" / "mev"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestBuilderSim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bs = load_module("builder_sim", MEV_DIR / "builder_sim.py")

    def test_profitable_bundle(self):
        sim = self.bs.simulate_bundle(gross_profit_wei=10**18, network_fee_wei=10**15, builder_tip_wei=10**14)
        self.assertTrue(sim["should_execute"])
        self.assertFalse(sim["would_submit"])

    def test_tip_kills_profit(self):
        sim = self.bs.simulate_bundle(gross_profit_wei=10**17, network_fee_wei=10**15, builder_tip_wei=10**18)
        self.assertFalse(sim["should_execute"])
        self.assertEqual(sim["skip_reason"], "builder_tip_exceeds_gross")


class TestMempoolLiveDedup(unittest.TestCase):
    def test_normalize_swap(self):
        fm = load_module("fork_mempool", MEV_DIR / "fork_mempool.py")
        tx = {
            "hash": "0xabc",
            "from": "0x1",
            "to": fm.PANCAKE_ROUTER,
            "value": hex(10**18),
            "input": "0x7ff36ab5" + "00" * 64,
        }
        self.assertTrue(fm.is_swap_candidate(tx, router=fm.PANCAKE_ROUTER))


if __name__ == "__main__":
    unittest.main()
