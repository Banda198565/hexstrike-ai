#!/usr/bin/env python3
"""Tests for unified Web3 audit MCP — offline-safe."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp import web3_audit_providers as api
from hexstrike.mcp import web3_audit_runner as war

ADDR = "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA"


def test_detect_stack() -> None:
    r = war.detect_web3_audit_stack()
    assert r["success"]
    assert "api_env" in r
    assert r["api_env"]["GOPLUS"] is True


def test_forta_skipped_without_key() -> None:
    import os
    with patch.dict(os.environ, {"FORTA_API_KEY": ""}, clear=False):
        r = api.forta_get_alerts(address=ADDR)
    assert r.get("skipped") is True


def test_mythx_skipped_without_key() -> None:
    r = api.mythx_deep_scan("/nonexistent.sol")
    assert r.get("skipped") or not r.get("success")


def test_revoke_list_approvals_shape() -> None:
    r = api.revoke_list_approvals(ADDR)
    assert r["success"]
    assert "revoke.cash" in r["revoke_url"]
    assert r["read_only"] is True


def test_docs_search() -> None:
    r = api.docs_search("slither")
    assert r["success"]
    assert r["hit_count"] >= 1


def test_scamsniffer_skipped() -> None:
    r = api.scamsniffer_tx_risk("0xdead")
    assert r.get("skipped")


def test_kerberus_skipped() -> None:
    r = api.kerberus_url_or_tx_risk("https://example.com")
    assert r.get("skipped")


def test_slither_critical_alias() -> None:
    src = "pragma solidity ^0.8.0; contract T { function f() public {} }"
    r = war.slither_find_critical_sinks(src, source_is_code=True)
    assert "critical_sinks" in r or "sink_count" in r


def test_registry_file_exists() -> None:
    reg = ROOT / "config/mcp/web3-audit-tools.registry.json"
    assert reg.is_file()
    import json
    data = json.loads(reg.read_text())
    assert len(data["tools"]) >= 30


def main() -> int:
    tests = [
        test_detect_stack,
        test_forta_skipped_without_key,
        test_mythx_skipped_without_key,
        test_revoke_list_approvals_shape,
        test_docs_search,
        test_scamsniffer_skipped,
        test_kerberus_skipped,
        test_slither_critical_alias,
        test_registry_file_exists,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
