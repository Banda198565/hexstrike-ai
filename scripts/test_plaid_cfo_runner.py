#!/usr/bin/env python3
"""Unit tests for Plaid CFO runner (offline-safe)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = __file__.replace("/scripts/test_plaid_cfo_runner.py", "")
sys.path.insert(0, ROOT + "/src")

from hexstrike.mcp import plaid_cfo_runner as pcr


class TestPlaidCfoRunner(unittest.TestCase):
    def test_detect_skipped_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            r = pcr.detect_plaid_config()
        self.assertTrue(r.get("success"))
        self.assertFalse(r.get("ready"))
        self.assertTrue(r.get("skipped"))

    def test_accounts_skipped_without_token(self):
        with patch.dict(os.environ, {"PLAID_CLIENT_ID": "x", "PLAID_SECRET": "y"}, clear=True):
            r = pcr.plaid_accounts_list()
        self.assertTrue(r.get("skipped"))

    def test_cfo_summary_skipped(self):
        with patch.dict(os.environ, {}, clear=True):
            r = pcr.plaid_cfo_summary()
        self.assertTrue(r.get("skipped"))


if __name__ == "__main__":
    unittest.main()
