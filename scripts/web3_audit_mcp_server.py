#!/usr/bin/env python3
"""HexStrike Unified Web3 Audit MCP — static, RPC, risk APIs, wallet hygiene.

Blocks:
  StaticAnalysis   — Slither, Mythril, MythX, Echidna, Aderyn
  TransactionRisk  — Forta, GoPlus, ScamSniffer, Pocket Universe, Kerberus, Web3 Antivirus
  WalletHygiene    — Revoke.cash (read-only)
  RPCInfra         — Chainstack, Alchemy, Infura/Tenderly
  Reports          — audit_reports_fetch, normalize, full_web3_audit

Credentials: MCP server env only (mcp.json) — never in agent prompts.
Policy: non-emulation — skipped:true when API/binary missing; never fabricate findings.

Usage:
  python3 scripts/web3_audit_mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.fastmcp import FastMCP

from hexstrike.mcp import solidity_audit_runner as sar
from hexstrike.mcp import web3_audit_providers as api
from hexstrike.mcp import web3_audit_runner as war
from hexstrike.mcp import web3_rpc_runner as rpc

mcp = FastMCP("web3_audit_mcp")


def _trace(tool: str, inp: dict, out: dict) -> None:
    trace_id = os.environ.get("HEXSTRIKE_TRACE_ID", "").strip()
    if not trace_id:
        return
    try:
        log_path = ROOT / "artifacts" / "workflow" / "traces" / f"{trace_id}.json"
        if not log_path.is_file():
            return
        data = json.loads(log_path.read_text(encoding="utf-8"))
        data.setdefault("steps", []).append(
            {
                "seq": len(data.get("steps", [])) + 1,
                "tool": tool,
                "tool_kind": "mcp",
                "phase": "web3_audit",
                "input": inp,
                "output": {"success": out.get("success"), "finding_count": out.get("finding_count")},
                "status": "success" if out.get("success") else "failed",
            }
        )
        log_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _out(result: dict, tool: str, inp: dict) -> str:
    _trace(tool, inp, result)
    return json.dumps(result, ensure_ascii=False)


# ── Stack / composite ─────────────────────────────────────────────────────────

@mcp.tool()
def detect_web3_audit_stack() -> str:
    """List local binaries (Slither/Mythril/Echidna) and configured API env flags."""
    return _out(war.detect_web3_audit_stack(), "detect_web3_audit_stack", {})


@mcp.tool()
def full_web3_audit(
    address: Optional[str] = None,
    source_or_path: Optional[str] = None,
    chain: str = "mainnet",
    source_is_code: bool = False,
) -> str:
    """Composite audit: static + RPC + GoPlus + normalize."""
    inp = {"address": address, "source_or_path": (source_or_path or "")[:120], "chain": chain}
    return _out(war.full_web3_audit(address=address, source_or_path=source_or_path, chain=chain, source_is_code=source_is_code), "full_web3_audit", inp)


@mcp.tool()
def normalize_findings(raw_findings_json: str) -> str:
    """Dedupe findings from multiple analyzers (JSON object keyed by source)."""
    try:
        raw = json.loads(raw_findings_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    return _out(sar.normalize_findings(raw), "normalize_findings", {"keys": list(raw.keys()) if isinstance(raw, dict) else "list"})


# ── StaticAnalysis ────────────────────────────────────────────────────────────

@mcp.tool()
def parse_contract(source_or_path: str, source_is_code: bool = False) -> str:
    """Parse Solidity — compiler version, contracts, framework."""
    inp = {"source_or_path": source_or_path[:200], "source_is_code": source_is_code}
    return _out(sar.parse_contract(source_or_path, source_is_code=source_is_code), "parse_contract", inp)


@mcp.tool()
def slither_run_detectors(source_or_path: str, source_is_code: bool = False, excluded_detectors: Optional[list[str]] = None) -> str:
    """Slither detectors with locations and swc_refs."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(sar.slither_run_detectors(source_or_path, source_is_code=source_is_code, excluded_detectors=excluded_detectors), "slither_run_detectors", inp)


@mcp.tool()
def slither_structure(source_or_path: str, source_is_code: bool = False) -> str:
    """Contract structure — state vars, call graph, entry points."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(sar.slither_structure(source_or_path, source_is_code=source_is_code), "slither_structure", inp)


@mcp.tool()
def slither_find_critical_sinks(source_or_path: str, source_is_code: bool = False) -> str:
    """High-impact sinks: delegatecall, transfers, reentrancy."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(war.slither_find_critical_sinks(source_or_path, source_is_code=source_is_code), "slither_find_critical_sinks", inp)


@mcp.tool()
def check_swc_patterns(source_or_path: str, source_is_code: bool = False) -> str:
    """SWC pattern issues with exploit_scenario_short."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(sar.check_swc_patterns(source_or_path, source_is_code=source_is_code), "check_swc_patterns", inp)


@mcp.tool()
def aderyn_analyze(source_or_path: str, source_is_code: bool = False, ruleset: str = "default") -> str:
    """Aderyn violations[] — property/status."""
    inp = {"source_or_path": source_or_path[:200], "ruleset": ruleset}
    return _out(sar.aderyn_analyze(source_or_path, source_is_code=source_is_code, ruleset=ruleset), "aderyn_analyze", inp)


@mcp.tool()
def mythril_scan_summary(
    bytecode: Optional[str] = None,
    address: Optional[str] = None,
    chain: str = "mainnet",
    source_or_path: Optional[str] = None,
    source_is_code: bool = False,
) -> str:
    """Mythril summary from bytecode, address, or source."""
    inp = {"address": address, "chain": chain}
    return _out(sar.mythril_scan_summary(bytecode=bytecode, address=address, chain=chain, path_or_source=source_or_path, source_is_code=source_is_code), "mythril_scan_summary", inp)


@mcp.tool()
def mythx_deep_scan(source_or_path: str, chain: str = "mainnet") -> str:
    """MythX cloud deep scan — requires MYTHX_API_KEY."""
    inp = {"source_or_path": source_or_path[:200], "chain": chain}
    return _out(api.mythx_deep_scan(source_or_path, chain=chain), "mythx_deep_scan", inp)


@mcp.tool()
def echidna_run_tests(source_or_path: str, source_is_code: bool = False) -> str:
    """Echidna property fuzzing on Foundry project."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(war.echidna_run_tests(source_or_path, source_is_code=source_is_code), "echidna_run_tests", inp)


@mcp.tool()
def web3_antivirus_scan(address: Optional[str] = None, source: Optional[str] = None, chain: str = "mainnet") -> str:
    """Web3 Antivirus ML scan — requires WEB3_ANTIVIRUS_API_KEY."""
    inp = {"address": address, "chain": chain}
    return _out(api.web3_antivirus_scan(address=address, source=source, chain=chain), "web3_antivirus_scan", inp)


@mcp.tool()
def contract_security_score(source_or_path: str, source_is_code: bool = False, include_mythril: bool = False) -> str:
    """Triage score 0–100, grade A–F."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(sar.contract_security_score(source_or_path, source_is_code=source_is_code, include_mythril=include_mythril), "contract_security_score", inp)


@mcp.tool()
def compile_and_abi(source_or_path: str, contract_name: Optional[str] = None) -> str:
    """Foundry compile — ABI/bytecode."""
    inp = {"source_or_path": source_or_path[:200]}
    return _out(sar.compile_and_abi(source_or_path, contract_name=contract_name), "compile_and_abi", inp)


@mcp.tool()
def generate_audit_report_skeleton(contract_name: str, purpose: str = "token") -> str:
    """Audit report section skeleton."""
    inp = {"contract_name": contract_name, "purpose": purpose}
    return _out(sar.generate_audit_report_skeleton(contract_name, purpose=purpose), "generate_audit_report_skeleton", inp)


# ── TransactionRisk ───────────────────────────────────────────────────────────

@mcp.tool()
def forta_get_alerts(address: Optional[str] = None, tx_hash: Optional[str] = None, chain: str = "mainnet") -> str:
    """Forta alerts — requires FORTA_API_KEY."""
    inp = {"address": address, "tx_hash": (tx_hash or "")[:18], "chain": chain}
    return _out(api.forta_get_alerts(address=address, tx_hash=tx_hash, chain=chain), "forta_get_alerts", inp)


@mcp.tool()
def forta_stream_threats(address: str, chain: str = "mainnet") -> str:
    """Forta threat snapshot for address."""
    inp = {"address": address, "chain": chain}
    return _out(api.forta_stream_threats(address, chain=chain), "forta_stream_threats", inp)


@mcp.tool()
def goplus_contract_risk(address: str, chain: str = "mainnet") -> str:
    """GoPlus token/contract risk API (public read-only)."""
    inp = {"address": address, "chain": chain}
    return _out(api.goplus_contract_risk(address, chain=chain), "goplus_contract_risk", inp)


@mcp.tool()
def scamsniffer_tx_risk(tx_data: str, chain: str = "mainnet") -> str:
    """ScamSniffer tx check — requires SCAMSNIFFER_API_KEY."""
    inp = {"chain": chain, "tx_data_len": len(tx_data)}
    return _out(api.scamsniffer_tx_risk(tx_data, chain=chain), "scamsniffer_tx_risk", inp)


@mcp.tool()
def pocket_universe_simulate(tx_data: str, chain: str = "mainnet") -> str:
    """Pocket Universe tx simulation — requires POCKET_UNIVERSE_API_KEY."""
    inp = {"chain": chain}
    return _out(api.pocket_universe_simulate(tx_data, chain=chain), "pocket_universe_simulate", inp)


@mcp.tool()
def kerberus_url_or_tx_risk(input_value: str, chain: str = "mainnet") -> str:
    """Kerberus URL or tx risk — requires KERBERUS_API_KEY."""
    inp = {"input": input_value[:80], "chain": chain}
    return _out(api.kerberus_url_or_tx_risk(input_value, chain=chain), "kerberus_url_or_tx_risk", inp)


# ── WalletHygiene ─────────────────────────────────────────────────────────────

@mcp.tool()
def revoke_list_approvals(address: str, chain: str = "mainnet") -> str:
    """Read-only approval surface + Revoke.cash link (no on-chain revoke from MCP)."""
    inp = {"address": address, "chain": chain}
    return _out(api.revoke_list_approvals(address, chain=chain), "revoke_list_approvals", inp)


# ── RPC / Infra ───────────────────────────────────────────────────────────────

@mcp.tool()
def detect_rpc_config() -> str:
    """RPC env status — redacted URLs."""
    return _out(rpc.detect_rpc_config(), "detect_rpc_config", {})


@mcp.tool()
def rpc_contract_audit(address: str, chain: str = "mainnet") -> str:
    """On-chain bytecode audit — opcodes, proxy."""
    inp = {"address": address, "chain": chain}
    return _out(rpc.rpc_contract_audit(address, chain=chain), "rpc_contract_audit", inp)


@mcp.tool()
def rpc_tx_trace(tx_hash: str, chain: str = "mainnet") -> str:
    """Tx trace/receipt analysis."""
    inp = {"tx_hash": tx_hash[:18], "chain": chain}
    return _out(rpc.rpc_tx_trace(tx_hash, chain=chain), "rpc_tx_trace", inp)


@mcp.tool()
def rpc_wallet_risk(address: str, chain: str = "mainnet") -> str:
    """Wallet/address heuristic risk."""
    inp = {"address": address, "chain": chain}
    return _out(rpc.rpc_wallet_risk(address, chain=chain), "rpc_wallet_risk", inp)


@mcp.tool()
def rpc_event_intel(address: str, chain: str = "mainnet", topic: Optional[str] = None, from_block: str = "latest", to_block: str = "latest") -> str:
    """eth_getLogs aggregation."""
    inp = {"address": address, "chain": chain}
    return _out(rpc.rpc_event_intel(address, chain=chain, topic=topic, from_block=from_block, to_block=to_block), "rpc_event_intel", inp)


@mcp.tool()
def onchain_metadata(address: str, chain: str = "mainnet") -> str:
    """Proxy detection, implementation address."""
    inp = {"address": address, "chain": chain}
    return _out(sar.onchain_metadata(address, chain=chain), "onchain_metadata", inp)


@mcp.tool()
def chainstack_rpc_call(chain: str, method: str, params_json: str = "[]") -> str:
    """Generic JSON-RPC via CHAINSTACK_RPC_URL or WEB3_RPC_URL."""
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError:
        params = []
    inp = {"chain": chain, "method": method}
    return _out(api.chainstack_rpc_call(chain, method, params), "chainstack_rpc_call", inp)


@mcp.tool()
def chainstack_indexer_query(chain: str, query: str) -> str:
    """Chainstack indexer query — requires CHAINSTACK_INDEXER_URL."""
    inp = {"chain": chain, "query_len": len(query)}
    return _out(api.chainstack_indexer_query(chain, query), "chainstack_indexer_query", inp)


@mcp.tool()
def docs_search(term: str) -> str:
    """Search local HexStrike Web3 audit docs."""
    inp = {"term": term}
    return _out(api.docs_search(term), "docs_search", inp)


@mcp.tool()
def tenderly_simulate(tx_json: str, chain: str = "mainnet") -> str:
    """Tenderly tx simulation — requires TENDERLY_* env."""
    try:
        tx = json.loads(tx_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"invalid tx_json: {exc}"})
    inp = {"chain": chain}
    return _out(api.tenderly_simulate(tx, chain=chain), "tenderly_simulate", inp)


@mcp.tool()
def alchemy_get_nft_metadata(address: str, token_id: str, chain: str = "mainnet") -> str:
    """Alchemy NFT metadata — requires ALCHEMY_API_KEY."""
    inp = {"address": address, "token_id": token_id, "chain": chain}
    return _out(api.alchemy_get_nft_metadata(address, token_id, chain=chain), "alchemy_get_nft_metadata", inp)


@mcp.tool()
def infura_get_logs(address: str, chain: str = "mainnet", topics_json: str = "[]", from_block: str = "latest", to_block: str = "latest") -> str:
    """eth_getLogs via Infura/WEB3 RPC."""
    try:
        topics = json.loads(topics_json)
    except json.JSONDecodeError:
        topics = []
    inp = {"address": address, "chain": chain}
    return _out(api.infura_get_logs(address, topics=topics, from_block=from_block, to_block=to_block, chain=chain), "infura_get_logs", inp)


# ── Audit reports ─────────────────────────────────────────────────────────────

@mcp.tool()
def audit_reports_fetch(project: Optional[str] = None, address: Optional[str] = None) -> str:
    """Public audit report metadata — optional AUDIT_REPORTS_API_KEY."""
    inp = {"project": project, "address": address}
    return _out(api.audit_reports_fetch(project=project, address=address), "audit_reports_fetch", inp)


if __name__ == "__main__":
    mcp.run()
