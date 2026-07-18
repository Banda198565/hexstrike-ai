"""Solidity / EVM audit runner — real Slither/Mythril/RPC only, no fabricated findings."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexstrike.integrations.rpc_client import StealthRpcClient
from hexstrike.paths import ROOT, RPC_CONFIG
from hexstrike.skills.contract_toolchain import ContractToolchain, ToolResult

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = _REPO_ROOT / "artifacts" / "solidity-audit"

# Lightweight SWC hint map (Slither check name fragments → SWC id)
_SLITHER_SWC_HINTS: dict[str, str] = {
    "reentrancy": "SWC-107",
    "arbitrary-send-eth": "SWC-105",
    "suicidal": "SWC-106",
    "unprotected-upgrade": "SWC-125",
    "tx-origin": "SWC-115",
    "weak-prng": "SWC-120",
    "unchecked-lowlevel": "SWC-104",
    "delegatecall": "SWC-112",
    "controlled-delegatecall": "SWC-112",
}

_OZ_IMPORT_RE = re.compile(r'import\s+["\']@openzeppelin/contracts/', re.I)
_OZ_GUARD_RE = re.compile(r"\b(ReentrancyGuard|Ownable|AccessControl|Pausable)\b")
_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.I)
_CONTRACT_RE = re.compile(r"\bcontract\s+(\w+)", re.I)
_IMPORT_RE = re.compile(r'import\s+[^;]+;')


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(path_or_source: str, *, source_is_code: bool = False) -> tuple[Path | None, str | None]:
    """Return (path, inline_source)."""
    if source_is_code or "\n" in path_or_source or path_or_source.strip().startswith("pragma"):
        return None, path_or_source
    p = Path(path_or_source)
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    if p.is_file():
        return p, None
    return None, path_or_source


def _read_source(path: Path | None, inline: str | None) -> tuple[str, str]:
    if path:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, str(path)
    assert inline is not None
    return inline, "<inline-source>"


def parse_contract(source_or_path: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Normalize contract source metadata — no simulated vulnerability data."""
    path, inline = _resolve_path(source_or_path, source_is_code=source_is_code)
    if path is None and inline is None:
        return {"success": False, "error": "path not found and no source provided", "contracts": []}

    text, label = _read_source(path, inline)
    pragmas = _PRAGMA_RE.findall(text)
    contracts = _CONTRACT_RE.findall(text)
    imports = _IMPORT_RE.findall(text)

    return {
        "success": True,
        "source_label": label,
        "path": str(path) if path else None,
        "line_count": len(text.splitlines()),
        "pragma_versions": pragmas,
        "contracts": contracts,
        "import_count": len(imports),
        "imports_sample": imports[:10],
        "uses_openzeppelin_import": bool(_OZ_IMPORT_RE.search(text)),
    }


def _tool_to_mcp(result: ToolResult, *, audit_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "success": result.ok and not result.skipped,
        "audit_id": audit_id,
        "tool": result.tool,
        "findings": result.findings,
        "finding_count": len(result.findings),
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
    }
    if extra:
        out.update(extra)
    return out


def run_static_analysis_slither(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Run real Slither — returns empty findings if none (never fabricated)."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline = _resolve_path(path_or_source, source_is_code=source_is_code)

    if path is None:
        if inline is None:
            return {"success": False, "error": "slither requires a file path", "findings": [], "audit_id": audit_id}
        tmp = DEFAULT_ARTIFACTS / "inline" / f"{audit_id}.sol"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(inline, encoding="utf-8")
        path = tmp

    toolchain = ContractToolchain()
    result = toolchain.slither_scan(path)
    return _tool_to_mcp(result, audit_id=audit_id, extra={"path": str(path)})


def run_bytecode_scan_mythril(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Run real Mythril on source file — empty findings if clean or tool missing."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline = _resolve_path(path_or_source, source_is_code=source_is_code)

    if path is None:
        if inline is None:
            return {"success": False, "error": "mythril requires a file path", "findings": [], "audit_id": audit_id}
        tmp = DEFAULT_ARTIFACTS / "inline" / f"{audit_id}.sol"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(inline, encoding="utf-8")
        path = tmp

    toolchain = ContractToolchain()
    result = toolchain.mythril_analyze(path)
    return _tool_to_mcp(result, audit_id=audit_id, extra={"path": str(path)})


def check_swc_patterns(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Map Slither/Mythril output + light source heuristics to SWC hints — read-only."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    slither = run_static_analysis_slither(path_or_source, source_is_code=source_is_code)
    path, inline = _resolve_path(path_or_source, source_is_code=source_is_code)
    text, _ = _read_source(path, inline if path is None else None)

    swc_matches: list[dict[str, Any]] = []
    for f in slither.get("findings") or []:
        check = (f.get("check") or "").lower()
        for fragment, swc in _SLITHER_SWC_HINTS.items():
            if fragment in check:
                swc_matches.append(
                    {
                        "swc_id": swc,
                        "source": "slither",
                        "check": f.get("check"),
                        "impact": f.get("impact"),
                        "description": f.get("description"),
                    }
                )
                break

    # Source heuristics only — not findings fabrication, pattern flags for auditor review
    if re.search(r"\.call\{value:", text) and "nonReentrant" not in text and "ReentrancyGuard" not in text:
        swc_matches.append(
            {
                "swc_id": "SWC-107",
                "source": "source_heuristic",
                "check": "external-call-with-value-without-guard",
                "description": "Review reentrancy on ETH transfer via .call{value:}",
            }
        )
    if re.search(r"tx\.origin", text):
        swc_matches.append(
            {
                "swc_id": "SWC-115",
                "source": "source_heuristic",
                "check": "tx-origin-usage",
                "description": "tx.origin used — authentication risk",
            }
        )

    report_path = DEFAULT_ARTIFACTS / f"{audit_id}-swc.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "success": True,
        "audit_id": audit_id,
        "swc_matches": swc_matches,
        "match_count": len(swc_matches),
        "slither_skipped": slither.get("skipped"),
        "raw_report_path": str(report_path),
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def check_openzeppelin_rules(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """OpenZeppelin-style hygiene checks (imports, guards) — heuristic, not OZ MCP substitute."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline = _resolve_path(path_or_source, source_is_code=source_is_code)
    text, label = _read_source(path, inline if path is None else None)

    notes: list[dict[str, str]] = []
    has_oz = bool(_OZ_IMPORT_RE.search(text))
    guards = _OZ_GUARD_RE.findall(text)

    if has_oz and not guards:
        notes.append(
            {
                "rule": "oz-guard-missing",
                "severity": "info",
                "message": "OpenZeppelin imported but no Ownable/ReentrancyGuard/AccessControl detected",
            }
        )
    if re.search(r"function\s+\w+\([^)]*\)\s+public\s+", text) and "onlyOwner" not in text and "AccessControl" not in text:
        notes.append(
            {
                "rule": "oz-access-control-review",
                "severity": "medium",
                "message": "Public functions without obvious access modifier — manual review",
            }
        )

    return {
        "success": True,
        "audit_id": audit_id,
        "source_label": label,
        "uses_openzeppelin_import": has_oz,
        "detected_guards": guards,
        "notes": notes,
        "note_count": len(notes),
        "_disclaimer": "Heuristic OZ checks — for full OZ Contracts MCP integrate openzeppelin/contracts-mcp separately",
    }


def fetch_onchain_data(address: str, chain: str = "ethereum") -> dict[str, Any]:
    """Read-only on-chain fetch: bytecode + is_contract — no signing, no txs."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    addr = address.strip().lower()
    if not re.match(r"^0x[0-9a-f]{40}$", addr):
        return {"success": False, "error": "invalid address", "audit_id": audit_id}

    try:
        client = StealthRpcClient(RPC_CONFIG)
        _, resp = client.call("eth_getCode", [addr, "latest"], timeout=12.0)
        code = (resp.get("result") or "0x").lower()
        body = code[2:] if code.startswith("0x") else code
        return {
            "success": True,
            "audit_id": audit_id,
            "address": addr,
            "chain": chain,
            "is_contract": len(body) > 0,
            "bytecode_length": len(body) // 2,
            "bytecode_prefix": body[:64] if body else "",
            "read_only": True,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "audit_id": audit_id, "address": addr, "chain": chain}


def detect_audit_tools() -> dict[str, Any]:
    """Report which local audit binaries are available."""
    toolchain = ContractToolchain()
    tools = toolchain.detect_tools()
    return {"success": True, "tools": tools, "available": [k for k, v in tools.items() if v]}


def full_audit(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Ordered pipeline: parse → slither → swc → oz rules — real tools only."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    parsed = parse_contract(path_or_source, source_is_code=source_is_code)
    slither = run_static_analysis_slither(path_or_source, source_is_code=source_is_code)
    swc = check_swc_patterns(path_or_source, source_is_code=source_is_code)
    oz = check_openzeppelin_rules(path_or_source, source_is_code=source_is_code)

    report = {
        "success": parsed.get("success", False),
        "audit_id": audit_id,
        "parse": parsed,
        "slither": slither,
        "swc": swc,
        "openzeppelin": oz,
        "total_findings": (slither.get("finding_count") or 0) + (swc.get("match_count") or 0),
    }
    report_path = DEFAULT_ARTIFACTS / f"{audit_id}-full.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["raw_report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
