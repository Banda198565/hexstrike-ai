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


def test_dedupe_and_security_score() -> None:
    from hexstrike.mcp.solidity_audit_runner import _dedupe_vulnerabilities, _normalize_vulnerability, _security_score

    a = _normalize_vulnerability({"check": "reentrancy-eth", "impact": "High", "description": "x"}, tool="slither")
    b = _normalize_vulnerability({"check": "reentrancy-eth", "impact": "High", "description": "x"}, tool="slither")
    c = _normalize_vulnerability({"check": "tx-origin", "impact": "Medium", "description": "y"}, tool="swc")
    deduped = _dedupe_vulnerabilities([a, b, c])
    assert len(deduped) == 2
    assert _security_score(deduped) > 0


def test_slither_functions_fallback() -> None:
    from hexstrike.mcp.solidity_audit_runner import slither_functions

    src = "pragma solidity ^0.8.0; contract T { function foo() public {} modifier onlyX() {} }"
    r = slither_functions(src, source_is_code=True)
    assert r["success"]
    assert r["function_count"] >= 1


def test_scan_contract_inline() -> None:
    from hexstrike.mcp.solidity_audit_runner import scan_contract

    r = scan_contract(SAMPLE, source_is_code=True)
    assert r["success"]
    assert "security_score" in r
    assert "vulnerabilities" in r


def main() -> int:
    tests = [
        test_parse_contract_inline,
        test_check_oz_rules,
        test_swc_heuristic_tx_origin,
        test_detect_tools,
        test_dedupe_and_security_score,
        test_slither_functions_fallback,
        test_scan_contract_inline,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
