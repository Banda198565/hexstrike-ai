#!/usr/bin/env python3
"""HexStrike Solidity Audit MCP Server — real Slither/Mythril/RPC, no simulated findings.

Tools:
  - parse_contract
  - run_static_analysis_slither
  - run_bytecode_scan_mythril
  - check_swc_patterns
  - check_openzeppelin_rules
  - fetch_onchain_data
  - detect_audit_tools
  - full_audit

Env:
  SOLIDITY_AUDIT_ARTIFACTS_DIR — default artifacts/solidity-audit
  RPC config via hexstrike paths (read-only eth_getCode)

Usage:
  python3 scripts/solidity_audit_mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.fastmcp import FastMCP

from hexstrike.mcp import solidity_audit_runner as sar

mcp = FastMCP("solidity_audit_mcp")


def _maybe_trace(tool: str, input_data: dict, output: dict) -> None:
    trace_id = os.environ.get("HEXSTRIKE_TRACE_ID", "").strip()
    if not trace_id:
        return
    try:
        log_path = ROOT / "artifacts" / "workflow" / "traces" / f"{trace_id}.json"
        if not log_path.is_file():
            return
        data = json.loads(log_path.read_text(encoding="utf-8"))
        seq = len(data.get("steps", [])) + 1
        data.setdefault("steps", []).append(
            {
                "seq": seq,
                "tool": tool,
                "tool_kind": "mcp",
                "phase": "contract_audit",
                "input": input_data,
                "output": {
                    "success": output.get("success"),
                    "finding_count": output.get("finding_count") or output.get("match_count"),
                    "raw_report_path": output.get("raw_report_path"),
                },
                "status": "success" if output.get("success") else "failed",
            }
        )
        log_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


@mcp.tool()
def parse_contract(source_or_path: str, source_is_code: bool = False) -> str:
    """Parse Solidity source or file path — metadata only (pragma, contracts, imports)."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.parse_contract(source_or_path, source_is_code=source_is_code)
    _maybe_trace("parse_contract", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def run_static_analysis_slither(source_or_path: str, source_is_code: bool = False) -> str:
    """Run real Slither JSON output. Empty findings if clean — never fabricated."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.run_static_analysis_slither(source_or_path, source_is_code=source_is_code)
    _maybe_trace("run_static_analysis_slither", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def run_bytecode_scan_mythril(source_or_path: str, source_is_code: bool = False) -> str:
    """Run real Mythril on Solidity source file. Skipped if mythril not installed."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.run_bytecode_scan_mythril(source_or_path, source_is_code=source_is_code)
    _maybe_trace("run_bytecode_scan_mythril", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def check_swc_patterns(source_or_path: str, source_is_code: bool = False) -> str:
    """Map Slither + source heuristics to SWC-style pattern hints."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.check_swc_patterns(source_or_path, source_is_code=source_is_code)
    _maybe_trace("check_swc_patterns", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def check_openzeppelin_rules(source_or_path: str, source_is_code: bool = False) -> str:
    """Heuristic OpenZeppelin import/guard hygiene checks (not full OZ MCP)."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.check_openzeppelin_rules(source_or_path, source_is_code=source_is_code)
    _maybe_trace("check_openzeppelin_rules", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def fetch_onchain_data(address: str, chain: str = "ethereum") -> str:
    """Read-only eth_getCode — bytecode length/prefix. No signing or transactions."""
    inp = {"address": address, "chain": chain}
    result = sar.fetch_onchain_data(address, chain=chain)
    _maybe_trace("fetch_onchain_data", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def slither_run_detectors(source_or_path: str, source_is_code: bool = False) -> str:
    """Run all Slither detectors — normalized JSON findings."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.slither_run_detectors(source_or_path, source_is_code=source_is_code)
    _maybe_trace("slither_run_detectors", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def slither_functions(source_or_path: str, source_is_code: bool = False) -> str:
    """List contract functions and modifiers (Slither JSON or source fallback)."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.slither_functions(source_or_path, source_is_code=source_is_code)
    _maybe_trace("slither_functions", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def slither_critical_sinks(source_or_path: str, source_is_code: bool = False) -> str:
    """High-impact sinks: delegatecall, transfers, reentrancy patterns from Slither."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.slither_critical_sinks(source_or_path, source_is_code=source_is_code)
    _maybe_trace("slither_critical_sinks", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def run_aderyn(source_or_path: str, source_is_code: bool = False) -> str:
    """Run real Aderyn static analysis. Skipped if aderyn not installed."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.run_aderyn(source_or_path, source_is_code=source_is_code)
    _maybe_trace("run_aderyn", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_vulnerabilities(source_or_path: str, source_is_code: bool = False) -> str:
    """Aggregated deduplicated vulnerability list with security_score."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.list_vulnerabilities(source_or_path, source_is_code=source_is_code)
    _maybe_trace("list_vulnerabilities", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def scan_contract(source_or_path: str, source_is_code: bool = False) -> str:
    """Quick aggregated scan: parse + vulnerabilities + critical sinks + security_score."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.scan_contract(source_or_path, source_is_code=source_is_code)
    _maybe_trace("scan_contract", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def detect_audit_tools() -> str:
    """List locally available audit tools (slither, mythril, forge, echidna)."""
    result = sar.detect_audit_tools()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def full_audit(source_or_path: str, source_is_code: bool = False) -> str:
    """Pipeline: parse → slither → SWC → OZ heuristics. Real tools only."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    result = sar.full_audit(source_or_path, source_is_code=source_is_code)
    _maybe_trace("full_audit", inp, result)
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
