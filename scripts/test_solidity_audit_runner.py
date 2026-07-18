#!/usr/bin/env python3
"""Unit tests for solidity audit runner — no Slither/Mythril binary required."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp.solidity_audit_runner import (
    check_openzeppelin_rules,
    check_swc_patterns,
    detect_audit_tools,
    parse_contract,
)

SAMPLE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
contract Vulnerable {
    function withdraw() public {
        (bool ok,) = msg.sender.call{value: address(this).balance}("");
        require(ok);
    }
}
"""


def test_parse_contract_inline() -> None:
    r = parse_contract(SAMPLE, source_is_code=True)
    assert r["success"]
    assert "Vulnerable" in r["contracts"]
    assert r["uses_openzeppelin_import"]


def test_check_oz_rules() -> None:
    r = check_openzeppelin_rules(SAMPLE, source_is_code=True)
    assert r["success"]
    assert r["uses_openzeppelin_import"]
    assert any(n["rule"] == "oz-guard-missing" for n in r["notes"])


def test_swc_heuristic_tx_origin() -> None:
    src = "pragma solidity ^0.8.0; contract C { function f() public { require(tx.origin == msg.sender); } }"
    r = check_swc_patterns(src, source_is_code=True)
    assert r["success"]
    assert any(m.get("swc_id") == "SWC-115" for m in r["swc_matches"])


def test_detect_tools() -> None:
    r = detect_audit_tools()
    assert r["success"]
    assert "tools" in r


def main() -> int:
    for fn in [
        test_parse_contract_inline,
        test_check_oz_rules,
        test_swc_heuristic_tx_origin,
        test_detect_tools,
    ]:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {4} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
