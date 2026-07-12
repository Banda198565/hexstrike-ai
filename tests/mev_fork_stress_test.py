#!/usr/bin/env python3
"""Offline tests for BSC fork mempool classification (Variant D)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEV_DIR = ROOT / "scripts" / "sandbox" / "mev"
sys.path.insert(0, str(MEV_DIR))


def load_fork_mempool():
    spec = importlib.util.spec_from_file_location("fork_mempool", MEV_DIR / "fork_mempool.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules["fork_mempool"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestForkMempool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fm = load_fork_mempool()

    def test_swap_candidate_pancake_eth_swap(self):
        tx = {
            "hash": "0xabc",
            "from": "0x1",
            "to": self.fm.PANCAKE_ROUTER,
            "value": hex(5 * 10**18),
            "input": "0x7ff36ab5" + "00" * 120,
        }
        self.assertTrue(self.fm.is_swap_candidate(tx, router=self.fm.PANCAKE_ROUTER))

    def test_rejects_non_router_target(self):
        tx = {
            "to": "0x0000000000000000000000000000000000000001",
            "value": hex(10**18),
            "input": "0x7ff36ab5" + "00" * 120,
        }
        self.assertFalse(self.fm.is_swap_candidate(tx, router=self.fm.PANCAKE_ROUTER))

    def test_rejects_zero_value_eth_swap(self):
        tx = {
            "to": self.fm.PANCAKE_ROUTER,
            "value": "0x0",
            "input": "0x7ff36ab5" + "00" * 120,
        }
        self.assertFalse(self.fm.is_swap_candidate(tx, router=self.fm.PANCAKE_ROUTER))

    def test_normalize_candidate_fields(self):
        tx = {
            "hash": "0xdead",
            "from": "0x2",
            "to": self.fm.PANCAKE_ROUTER,
            "value": hex(2 * 10**18),
            "input": "0xb6f9de95" + "00" * 100,
            "gasPrice": hex(3 * 10**9),
        }
        out = self.fm.normalize_candidate(tx, 56)
        self.assertEqual(out["value_wei"], 2 * 10**18)
        self.assertEqual(out["selector_name"], "swapExactETHForTokensSupportingFeeOnTransferTokens")
        self.assertEqual(out["chain_id"], 56)


if __name__ == "__main__":
    unittest.main()
