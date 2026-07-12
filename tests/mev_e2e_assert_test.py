#!/usr/bin/env python3
"""Unit tests for mev_e2e_assert invariants (offline JSON fixtures)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSERT_PATH = ROOT / "scripts" / "sandbox" / "mev" / "mev_e2e_assert.py"


def load_assert_module():
    spec = importlib.util.spec_from_file_location("mev_e2e_assert", ASSERT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules["mev_e2e_assert"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestMevE2eAssert(unittest.TestCase):
    def setUp(self):
        self.mod = load_assert_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.art = Path(self.tmp.name)
        self.mod.SANDBOX_ART = self.art
        self.mod.ROOT = ROOT

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, payload: dict) -> None:
        (self.art / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_full_stack_pass(self):
        self._write("mev-mempool-scan.json", {"rpc": "http://127.0.0.1:8545", "candidates": []})
        self._write(
            "mev-sandwich-result.json",
            {"amm": "0x" + "a" * 40, "profit_wei": 100, "success": True},
        )
        self._write(
            "mev-jit-result.json",
            {
                "pool": "0x" + "b" * 40,
                "skipped": False,
                "net_after_gas_wei": 50,
                "success": True,
                "classifier": {"should_execute": True},
            },
        )
        self._write(
            "mev-backrun-result.json",
            {
                "pool_a": "0x" + "c" * 40,
                "pool_b": "0x" + "d" * 40,
                "router": "0x" + "e" * 40,
                "profit_wei": 200,
                "success": True,
                "skipped": False,
            },
        )
        report = self.mod.Report(ts="t", mode="full-stack", passed=False)
        self.mod.assert_full_stack(report)
        report.finalize()
        self.assertTrue(report.passed)

    def test_jit_skip_gate_pass(self):
        self._write(
            "mev-jit-skip-gate.json",
            {
                "skipped": True,
                "success": False,
                "skip_reason": "gas_exceeds_fee_share",
                "classifier": {"should_execute": False, "skip_reason": "gas_exceeds_fee_share"},
            },
        )
        report = self.mod.Report(ts="t", mode="jit-skip-gate", passed=False)
        self.mod.assert_jit_skip_gate(report)
        report.finalize()
        self.assertTrue(report.passed)

    def test_redteam_pass(self):
        runs = [
            {"scenario": s, "outcome": "VULN_CONFIRMED", "detail": "ok"}
            for s in (
                "08-mev-sandwich-sim",
                "09-mev-frontrun-gas-race",
                "10-mev-jit-liquidity",
                "11-mev-backrun-arb",
            )
        ]
        self._write("redteam-report.json", {"runs": runs})
        report = self.mod.Report(ts="t", mode="redteam", passed=False)
        self.mod.assert_redteam(report)
        report.finalize()
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
