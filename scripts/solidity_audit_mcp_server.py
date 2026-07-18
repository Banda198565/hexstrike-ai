#!/usr/bin/env python3
"""HexStrike Solidity Audit MCP Server — real Slither/Mythril/RPC, no simulated findings.

Auditor workflow (recommended):
  1. parse_contract
  2. slither_run_detectors + check_swc_patterns
  3. slither_structure (attack surface)
  4. aderyn_analyze (if installed)
  5. onchain_metadata + mythril_scan_summary (deployed addresses)
  6. normalize_findings → generate_audit_report_skeleton

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
                    "finding_count": output.get("finding_count")
                    or output.get("match_count")
                    or output.get("issue_count")
                    or output.get("detector_count"),
                    "raw_report_path": output.get("raw_report_path"),
                },
                "status": "success" if output.get("success") else "failed",
            }
        )
        log_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _dump(result: dict, tool: str, inp: dict) -> str:
    _maybe_trace(tool, inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def parse_contract(source_or_path: str, source_is_code: bool = False) -> str:
    """Parse Solidity source — compiler version, contracts, inheritance, entry points, framework."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.parse_contract(source_or_path, source_is_code=source_is_code), "parse_contract", inp)


@mcp.tool()
def slither_run_detectors(
    source_or_path: str,
    source_is_code: bool = False,
    excluded_detectors: Optional[list[str]] = None,
) -> str:
    """Run Slither detectors — returns detectors[] with severity, locations, swc_refs."""
    inp = {
        "source_or_path": source_or_path[:200],
        "source_is_code": source_is_code,
        "excluded_detectors": excluded_detectors,
    }
    return _dump(
        sar.slither_run_detectors(
            source_or_path,
            source_is_code=source_is_code,
            excluded_detectors=excluded_detectors,
        ),
        "slither_run_detectors",
        inp,
    )


@mcp.tool()
def slither_structure(source_or_path: str, source_is_code: bool = False) -> str:
    """Contract structure: state variables, call graph hints, external entry points."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.slither_structure(source_or_path, source_is_code=source_is_code), "slither_structure", inp)


@mcp.tool()
def check_swc_patterns(source_or_path: str, source_is_code: bool = False) -> str:
    """SWC pattern matching — issues[] with exploit_scenario_short."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.check_swc_patterns(source_or_path, source_is_code=source_is_code), "check_swc_patterns", inp)


@mcp.tool()
def aderyn_analyze(
    source_or_path: str,
    source_is_code: bool = False,
    ruleset: str = "default",
) -> str:
    """Aderyn formal-style analysis — violations[] with property/status."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code, "ruleset": ruleset}
    return _dump(
        sar.aderyn_analyze(source_or_path, source_is_code=source_is_code, ruleset=ruleset),
        "aderyn_analyze",
        inp,
    )


@mcp.tool()
def mythril_scan_summary(
    bytecode: Optional[str] = None,
    address: Optional[str] = None,
    chain: str = "ethereum",
    source_or_path: Optional[str] = None,
    source_is_code: bool = False,
) -> str:
    """Mythril summary from bytecode, on-chain address, or source file."""
    inp = {
        "bytecode": (bytecode or "")[:80],
        "address": address,
        "chain": chain,
        "source_or_path": (source_or_path or "")[:200],
    }
    return _dump(
        sar.mythril_scan_summary(
            bytecode=bytecode,
            address=address,
            chain=chain,
            path_or_source=source_or_path,
            source_is_code=source_is_code,
        ),
        "mythril_scan_summary",
        inp,
    )


@mcp.tool()
def contract_security_score(
    source_or_path: str,
    source_is_code: bool = False,
    include_mythril: bool = False,
) -> str:
    """Triage score 0–100, grade A–F, severity metrics, top_risks."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(
        sar.contract_security_score(
            source_or_path,
            source_is_code=source_is_code,
            include_mythril=include_mythril,
        ),
        "contract_security_score",
        inp,
    )


@mcp.tool()
def onchain_metadata(address: str, chain: str = "ethereum") -> str:
    """Read-only on-chain metadata: proxy detection, implementation address."""
    inp = {"address": address, "chain": chain}
    return _dump(sar.onchain_metadata(address, chain=chain), "onchain_metadata", inp)


@mcp.tool()
def compile_and_abi(source_or_path: str, contract_name: Optional[str] = None) -> str:
    """Compile Foundry project — ABI and bytecode from out/ artifacts."""
    inp = {"source_or_path": source_or_path[:200], "contract_name": contract_name}
    return _dump(sar.compile_and_abi(source_or_path, contract_name=contract_name), "compile_and_abi", inp)


@mcp.tool()
def generate_audit_report_skeleton(contract_name: str, purpose: str = "token") -> str:
    """Standard audit report skeleton (summary, findings, risk matrix)."""
    inp = {"contract_name": contract_name, "purpose": purpose}
    return _dump(sar.generate_audit_report_skeleton(contract_name, purpose=purpose), "generate_audit_report_skeleton", inp)


@mcp.tool()
def normalize_findings(raw_findings_json: str) -> str:
    """Dedupe and merge findings from multiple analyzers. Input: JSON object or array."""
    try:
        raw = json.loads(raw_findings_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"invalid JSON: {exc}"})
    inp = {"keys": list(raw.keys()) if isinstance(raw, dict) else "list"}
    return _dump(sar.normalize_findings(raw), "normalize_findings", inp)


# Legacy / composite tools (backward compatible)
@mcp.tool()
def run_static_analysis_slither(source_or_path: str, source_is_code: bool = False) -> str:
    """Legacy alias — use slither_run_detectors for spec output."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.run_static_analysis_slither(source_or_path, source_is_code=source_is_code), "run_static_analysis_slither", inp)


@mcp.tool()
def run_bytecode_scan_mythril(source_or_path: str, source_is_code: bool = False) -> str:
    """Legacy Mythril on source file — prefer mythril_scan_summary."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.run_bytecode_scan_mythril(source_or_path, source_is_code=source_is_code), "run_bytecode_scan_mythril", inp)


@mcp.tool()
def check_openzeppelin_rules(source_or_path: str, source_is_code: bool = False) -> str:
    """Heuristic OpenZeppelin import/guard hygiene checks."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.check_openzeppelin_rules(source_or_path, source_is_code=source_is_code), "check_openzeppelin_rules", inp)


@mcp.tool()
def fetch_onchain_data(address: str, chain: str = "ethereum") -> str:
    """Legacy read-only eth_getCode — prefer onchain_metadata."""
    inp = {"address": address, "chain": chain}
    return _dump(sar.fetch_onchain_data(address, chain=chain), "fetch_onchain_data", inp)


@mcp.tool()
def slither_functions(source_or_path: str, source_is_code: bool = False) -> str:
    """List contract functions and modifiers."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.slither_functions(source_or_path, source_is_code=source_is_code), "slither_functions", inp)


@mcp.tool()
def slither_critical_sinks(source_or_path: str, source_is_code: bool = False) -> str:
    """High-impact sinks from Slither."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.slither_critical_sinks(source_or_path, source_is_code=source_is_code), "slither_critical_sinks", inp)


@mcp.tool()
def run_aderyn(source_or_path: str, source_is_code: bool = False) -> str:
    """Legacy Aderyn — prefer aderyn_analyze."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.run_aderyn(source_or_path, source_is_code=source_is_code), "run_aderyn", inp)


@mcp.tool()
def list_vulnerabilities(source_or_path: str, source_is_code: bool = False) -> str:
    """Aggregated deduplicated vulnerability list."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.list_vulnerabilities(source_or_path, source_is_code=source_is_code), "list_vulnerabilities", inp)


@mcp.tool()
def scan_contract(source_or_path: str, source_is_code: bool = False) -> str:
    """Quick aggregated scan."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.scan_contract(source_or_path, source_is_code=source_is_code), "scan_contract", inp)


@mcp.tool()
def detect_audit_tools() -> str:
    """List locally available audit tools."""
    return json.dumps(sar.detect_audit_tools(), ensure_ascii=False)


@mcp.tool()
def full_audit(source_or_path: str, source_is_code: bool = False) -> str:
    """Deep pipeline: parse → slither → swc → aderyn → oz → aggregated list."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _dump(sar.full_audit(source_or_path, source_is_code=source_is_code), "full_audit", inp)


if __name__ == "__main__":
    mcp.run()
