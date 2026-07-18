#!/usr/bin/env python3
"""Unit tests for Web3 RPC runner — no live RPC key required."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp import web3_rpc_runner as wrr

SAMPLE_ADDR = "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA"
SAMPLE_TX = "0x" + "a" * 64


def test_resolve_rpc_endpoint_env() -> None:
    with patch.dict(os.environ, {"WEB3_RPC_URL": "https://rpc.example.com/v3", "WEB3_RPC_KEY": "secret123"}):
        ep = wrr.resolve_rpc_endpoint("mainnet")
        assert ep["success"]
        assert ep["has_api_key"]
        assert "REDACTED" in ep["rpc_url_redacted"]
        assert "secret123" not in ep["rpc_url_redacted"]


def test_analyze_bytecode_delegatecall() -> None:
    # PUSH1 0x00 PUSH1 0x00 ... DELEGATECALL f4
    code = "0x60006000f460005260206000f3"
    analysis = wrr._analyze_bytecode(code)
    assert analysis["bytecode_length"] > 0
    assert any(o["name"] == "DELEGATECALL" for o in analysis["dangerous_opcodes"])


def test_rpc_contract_audit_invalid_address() -> None:
    r = wrr.rpc_contract_audit("not-an-address")
    assert not r["success"]


def test_rpc_tx_trace_invalid_hash() -> None:
    r = wrr.rpc_tx_trace("0x1234")
    assert not r["success"]


def test_rpc_wallet_risk_invalid() -> None:
    r = wrr.rpc_wallet_risk("bad")
    assert not r["success"]


def test_rpc_event_intel_invalid() -> None:
    r = wrr.rpc_event_intel("bad")
    assert not r["success"]


def test_detect_rpc_config_shape() -> None:
    r = wrr.detect_rpc_config()
    assert r["success"]
    assert "global_env" in r
    assert "chains" in r
    assert r["global_env"]["rpc_key_set"] in (True, False)


def test_normalize_chain_aliases() -> None:
    assert wrr._normalize_chain("ethereum") == "mainnet"
    assert wrr._normalize_chain("matic") == "polygon"


def test_redact_url() -> None:
    red = wrr._redact_url("https://mainnet.infura.io/v3/mysecretkey12345678")
    assert "mysecretkey" not in red
    assert "REDACTED" in red


def main() -> int:
    tests = [
        test_resolve_rpc_endpoint_env,
        test_analyze_bytecode_delegatecall,
        test_rpc_contract_audit_invalid_address,
        test_rpc_tx_trace_invalid_hash,
        test_rpc_wallet_risk_invalid,
        test_rpc_event_intel_invalid,
        test_detect_rpc_config_shape,
        test_normalize_chain_aliases,
        test_redact_url,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
