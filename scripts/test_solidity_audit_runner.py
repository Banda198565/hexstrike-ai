#!/usr/bin/env python3
"""Unit tests for solidity audit runner — no Slither/Mythril binary required."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp.solidity_audit_runner import (
    aderyn_analyze,
    check_openzeppelin_rules,
    check_swc_patterns,
    contract_security_score,
    detect_audit_tools,
    generate_audit_report_skeleton,
    normalize_findings,
    onchain_metadata,
    parse_contract,
    slither_structure,
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
    names = [c["name"] for c in r["contracts"]]
    assert "Vulnerable" in names
    assert r["uses_openzeppelin_import"]
    assert r["detected_framework"] == "bare"
    assert r["compiler_version"]


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
    assert any(i.get("swc_id") == "SWC-115" for i in r["issues"])
    assert r["issues"][0].get("exploit_scenario_short")


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


def test_slither_structure() -> None:
    r = slither_structure(SAMPLE, source_is_code=True)
    assert r["success"]
    assert r["contracts"]
    assert isinstance(r["external_entry_points"], list)


def test_normalize_findings() -> None:
    raw = {
        "slither": [{"id": "reentrancy-eth", "severity": "high", "description": "reenter"}],
        "swc": [{"swc_id": "SWC-107", "severity": "high", "description": "reenter"}],
    }
    r = normalize_findings(raw)
    assert r["success"]
    assert r["finding_count"] >= 1
    assert r["deduped_findings"][0]["sources"]


def test_contract_security_score() -> None:
    r = contract_security_score(SAMPLE, source_is_code=True)
    assert r["success"]
    assert 0 <= r["score"] <= 100
    assert r["grade"] in ("A", "B", "C", "D", "F")
    assert "metrics" in r


def test_generate_audit_report_skeleton() -> None:
    r = generate_audit_report_skeleton("MyToken", purpose="token")
    assert r["success"]
    assert "sections" in r
    assert "findings" in r["sections"]


def test_onchain_metadata_invalid() -> None:
    r = onchain_metadata("not-an-address")
    assert not r["success"]


def test_aderyn_analyze_skipped_shape() -> None:
    r = aderyn_analyze(SAMPLE, source_is_code=True)
    assert "violations" in r
    assert "ruleset" in r


def main() -> int:
    tests = [
        test_parse_contract_inline,
        test_check_oz_rules,
        test_swc_heuristic_tx_origin,
        test_detect_tools,
        test_dedupe_and_security_score,
        test_slither_functions_fallback,
        test_scan_contract_inline,
        test_slither_structure,
        test_normalize_findings,
        test_contract_security_score,
        test_generate_audit_report_skeleton,
        test_onchain_metadata_invalid,
        test_aderyn_analyze_skipped_shape,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
