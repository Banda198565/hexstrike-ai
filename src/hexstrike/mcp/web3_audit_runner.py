"""Unified Web3 audit runner — static, RPC, risk APIs, wallet hygiene (non-emulation)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexstrike.mcp import solidity_audit_runner as sar
from hexstrike.mcp import web3_audit_providers as providers
from hexstrike.mcp import web3_rpc_runner as rpc
from hexstrike.skills.contract_toolchain import ContractToolchain

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = _REPO_ROOT / "artifacts" / "web3-audit"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _audit_id(prefix: str = "w3") -> str:
    return f"{prefix}-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"


def _save_report(audit_id: str, payload: dict[str, Any], suffix: str) -> str:
    DEFAULT_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_ARTIFACTS / f"{audit_id}-{suffix}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _collect_findings(*results: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        for f in r.get("findings") or []:
            if isinstance(f, dict):
                out.append(f)
        for d in r.get("detectors") or []:
            out.append(
                {
                    "id": d.get("id"),
                    "source": "slither",
                    "category": d.get("id"),
                    "severity": d.get("severity"),
                    "description": d.get("description"),
                    "locations": d.get("locations"),
                    "swc_refs": d.get("swc_refs"),
                }
            )
        for i in r.get("issues") or []:
            out.append(
                {
                    "id": i.get("swc_id") or i.get("type"),
                    "source": r.get("source") or "unknown",
                    "category": i.get("type") or i.get("title"),
                    "severity": i.get("severity"),
                    "description": i.get("description") or i.get("exploit_scenario_short"),
                }
            )
    return out


def echidna_run_tests(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Run Echidna property tests on Foundry project — real binary only."""
    audit_id = _audit_id("echidna")
    path, inline, err = sar._prepare_sol_path(path_or_source, source_is_code=source_is_code, audit_id=audit_id)  # noqa: SLF001
    if err:
        return err
    project_dir = path.parent if path.is_file() else path
    toolchain = ContractToolchain()
    result = toolchain.echidna_fuzz(project_dir)
    findings: list[dict[str, Any]] = []
    if result.findings:
        findings = [{"source": "echidna", **f} for f in result.findings]
    elif result.ok and result.stdout:
        for line in result.stdout.splitlines():
            if "failed" in line.lower() or "error" in line.lower():
                findings.append(
                    {
                        "source": "echidna",
                        "category": "property-violation",
                        "severity": "high",
                        "description": line.strip(),
                    }
                )
    payload = {
        "success": result.ok or result.skipped,
        "audit_id": audit_id,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
        "findings": findings,
        "finding_count": len(findings),
        "project_dir": str(project_dir),
    }
    payload["raw_report_path"] = _save_report(audit_id, payload, "echidna")
    return payload


def slither_find_critical_sinks(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Alias: high-impact Slither sinks."""
    return sar.slither_critical_sinks(path_or_source, source_is_code=source_is_code)


def full_web3_audit(
    *,
    address: str | None = None,
    source_or_path: str | None = None,
    chain: str = "mainnet",
    source_is_code: bool = False,
) -> dict[str, Any]:
    """Composite pipeline: static + RPC + GoPlus + normalize."""
    audit_id = _audit_id("full")
    blocks: dict[str, Any] = {}

    if source_or_path:
        blocks["parse"] = sar.parse_contract(source_or_path, source_is_code=source_is_code)
        blocks["slither"] = sar.slither_run_detectors(source_or_path, source_is_code=source_is_code)
        blocks["swc"] = sar.check_swc_patterns(source_or_path, source_is_code=source_is_code)
        blocks["structure"] = sar.slither_structure(source_or_path, source_is_code=source_is_code)
        blocks["score"] = sar.contract_security_score(source_or_path, source_is_code=source_is_code)

    if address:
        blocks["rpc_contract"] = rpc.rpc_contract_audit(address, chain=chain)
        blocks["goplus"] = providers.goplus_contract_risk(address, chain=chain)
        blocks["wallet_risk"] = rpc.rpc_wallet_risk(address, chain=chain)
        blocks["onchain"] = sar.onchain_metadata(address, chain=chain)
        blocks["forta"] = providers.forta_get_alerts(address=address, chain=chain)

    raw_for_norm: dict[str, list[Any]] = {}
    for name, block in blocks.items():
        if block.get("findings"):
            raw_for_norm[name] = block["findings"]
        elif block.get("detectors"):
            raw_for_norm[name] = block["detectors"]
        elif block.get("issues"):
            raw_for_norm[name] = block["issues"]

    normalized = sar.normalize_findings(raw_for_norm) if raw_for_norm else {"deduped_findings": [], "finding_count": 0}

    payload = {
        "success": True,
        "audit_id": audit_id,
        "chain": chain,
        "address": address,
        "source_or_path": source_or_path,
        "blocks": blocks,
        "normalized": normalized,
        "total_findings": normalized.get("finding_count", 0),
        "read_only": True,
    }
    payload["raw_report_path"] = _save_report(audit_id, payload, "full")
    return payload


def detect_web3_audit_stack() -> dict[str, Any]:
    """Report configured backends and local binaries."""
    import os

    sar_tools = sar.detect_audit_tools()
    rpc_cfg = rpc.detect_rpc_config()
    env_flags = {
        "FORTA_API_KEY": bool(os.getenv("FORTA_API_KEY")),
        "GOPLUS": True,
        "MYTHX_API_KEY": bool(os.getenv("MYTHX_API_KEY")),
        "TENDERLY_ACCESS_KEY": bool(os.getenv("TENDERLY_ACCESS_KEY")),
        "ALCHEMY_API_KEY": bool(os.getenv("ALCHEMY_API_KEY")),
        "SCAMSNIFFER_API_KEY": bool(os.getenv("SCAMSNIFFER_API_KEY")),
        "POCKET_UNIVERSE_API_KEY": bool(os.getenv("POCKET_UNIVERSE_API_KEY")),
        "KERBERUS_API_KEY": bool(os.getenv("KERBERUS_API_KEY")),
        "WEB3_ANTIVIRUS_API_KEY": bool(os.getenv("WEB3_ANTIVIRUS_API_KEY")),
        "CHAINSTACK_RPC_URL": bool(os.getenv("CHAINSTACK_RPC_URL")),
        "WEB3_RPC_URL": bool(os.getenv("WEB3_RPC_URL")),
    }
    return {
        "success": True,
        "local_tools": sar_tools,
        "rpc": rpc_cfg,
        "api_env": env_flags,
        "read_only": True,
    }
