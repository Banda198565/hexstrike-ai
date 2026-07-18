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
_FUNCTION_RE = re.compile(
    r"function\s+(\w+)\s*\([^)]*\)\s*(public|external|internal|private)?",
    re.I,
)
_MODIFIER_RE = re.compile(r"modifier\s+(\w+)", re.I)
_INHERITANCE_RE = re.compile(r"\bcontract\s+(\w+)\s+is\s+([^{]+)\{", re.I)
_EVENT_RE = re.compile(r"event\s+(\w+)", re.I)
_STATE_VAR_RE = re.compile(
    r"\b(constant\s+)?(immutable\s+)?(public\s+|private\s+|internal\s+)?(\w+(?:\[\])?)\s+(\w+)\s*[;=]",
    re.I,
)
_LIBRARY_RE = re.compile(r"\blibrary\s+(\w+)", re.I)
_CALL_RE = re.compile(r"\b(\w+)\s*\(", re.I)

_EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

_SEVERITY_TO_GRADE: list[tuple[int, str]] = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]

_SWC_EXPLOIT_SCENARIOS: dict[str, str] = {
    "SWC-107": "Attacker re-enters before state update and drains ETH/tokens.",
    "SWC-105": "Unauthorized party sends contract ETH to arbitrary address.",
    "SWC-106": "Selfdestruct or unrestricted ETH send bricks funds or logic.",
    "SWC-125": "Proxy implementation can be upgraded without proper auth.",
    "SWC-115": "Phishing contract bypasses auth via tx.origin check.",
    "SWC-120": "Weak randomness enables predictable outcomes / gaming.",
    "SWC-104": "Unchecked low-level call return value hides failure.",
    "SWC-112": "Delegatecall to untrusted code overwrites storage.",
}

_FINDING_CATEGORIES: dict[str, str] = {
    "reentrancy": "reentrancy",
    "tx-origin": "auth",
    "arbitrary-send": "auth",
    "delegatecall": "upgrade-risk",
    "unprotected-upgrade": "upgrade-risk",
    "suicidal": "DoS",
    "unchecked": "logic",
    "weak-prng": "economic",
    "mint": "economic",
    "overflow": "logic",
}

_CRITICAL_SINK_FRAGMENTS = (
    "delegatecall",
    "send-eth",
    "transfer",
    "suicidal",
    "selfdestruct",
    "arbitrary-send",
    "unchecked-lowlevel",
    "reentrancy",
)

_SEVERITY_WEIGHT = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 2,
    "informational": 1,
    "info": 1,
}


def _prepare_sol_path(path_or_source: str, *, source_is_code: bool, audit_id: str) -> tuple[Path | None, str | None, dict[str, Any] | None]:
    """Resolve path; write inline source to temp file if needed."""
    path, inline = _resolve_path(path_or_source, source_is_code=source_is_code)
    if path is None:
        if inline is None:
            return None, None, {
                "success": False,
                "error": "path not found and no source provided",
                "audit_id": audit_id,
            }
        tmp = DEFAULT_ARTIFACTS / "inline" / f"{audit_id}.sol"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(inline, encoding="utf-8")
        path = tmp
    return path, inline, None


def _severity_weight(severity: str | None) -> int:
    return _SEVERITY_WEIGHT.get((severity or "info").lower(), 1)


def _map_swc_id(check: str | None) -> str | None:
    if not check:
        return None
    low = check.lower()
    for fragment, swc in _SLITHER_SWC_HINTS.items():
        if fragment in low:
            return swc
    return None


def _detect_framework(path: Path | None) -> str:
    if path is None:
        return "bare"
    search_dirs = [path.parent] if path.is_file() else [path]
    for d in search_dirs:
        for parent in [d, *d.parents]:
            if (parent / "foundry.toml").is_file():
                return "foundry"
            if (parent / "hardhat.config.js").is_file() or (parent / "hardhat.config.ts").is_file():
                return "hardhat"
            if parent == _REPO_ROOT.parent:
                break
    return "bare"


def _parse_contract_details(text: str) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for match in re.finditer(
        r"\bcontract\s+(\w+)(?:\s+is\s+([^{]+))?\s*\{",
        text,
        re.I,
    ):
        name = match.group(1)
        inheritance_raw = (match.group(2) or "").strip()
        inheritance = [p.strip() for p in inheritance_raw.split(",") if p.strip()] if inheritance_raw else []
        block_start = match.end()
        depth = 1
        i = block_start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        block = text[block_start : i - 1]
        modifiers = _MODIFIER_RE.findall(block)
        events = _EVENT_RE.findall(block)
        public_functions: list[str] = []
        external_functions: list[str] = []
        for fn_match in re.finditer(
            r"function\s+(\w+)\s*\([^)]*\)\s*((?:\w+\s+)*)",
            block,
            re.I,
        ):
            fn_name = fn_match.group(1)
            attrs = (fn_match.group(2) or "").lower()
            if "external" in attrs:
                external_functions.append(fn_name)
            elif "public" in attrs or not any(v in attrs for v in ("internal", "private")):
                public_functions.append(fn_name)
        contracts.append(
            {
                "name": name,
                "inheritance": inheritance,
                "modifiers": modifiers,
                "events": events,
                "public_functions": public_functions,
                "external_functions": external_functions,
            }
        )
    return contracts


def _slither_element_location(el: dict[str, Any]) -> dict[str, Any]:
    sm = el.get("source_mapping") or {}
    return {
        "file": sm.get("filename_absolute") or sm.get("filename_relative") or sm.get("filename"),
        "line": sm.get("lines", [None])[0] if sm.get("lines") else None,
        "function": el.get("name") if el.get("type") == "function" else el.get("name"),
    }


def _slither_detector_to_spec(det: dict[str, Any]) -> dict[str, Any]:
    check = det.get("check") or "unknown"
    impact = str(det.get("impact") or "informational").lower()
    locations: list[dict[str, Any]] = []
    for el in det.get("elements") or []:
        loc = _slither_element_location(el)
        if loc.get("file") or loc.get("function"):
            locations.append(loc)
    swc = _map_swc_id(check)
    return {
        "id": check,
        "title": check.replace("-", " ").title(),
        "severity": impact,
        "description": det.get("description") or "",
        "locations": locations,
        "swc_refs": [swc] if swc else [],
    }


def _infer_finding_category(label: str) -> str:
    low = label.lower()
    for fragment, category in _FINDING_CATEGORIES.items():
        if fragment in low:
            return category
    return "logic"


def _risk_grade(score: int) -> str:
    for threshold, grade in _SEVERITY_TO_GRADE:
        if score >= threshold:
            return grade
    return "F"


def _count_by_severity(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in items:
        sev = str(item.get("severity") or item.get("impact") or "low").lower()
        if sev in counts:
            counts[sev] += 1
        elif sev in ("informational", "info"):
            counts["low"] += 1
    return counts


def _normalize_vulnerability(item: dict[str, Any], *, tool: str) -> dict[str, Any]:
    check = item.get("check") or item.get("title") or item.get("name") or "unknown"
    impact = item.get("impact") or item.get("severity") or "info"
    desc = item.get("description") or item.get("message") or ""
    swc = item.get("swc_id") or _map_swc_id(str(check))
    return {
        "id": f"{tool}:{check}",
        "tool": tool,
        "category": check,
        "severity": str(impact).lower(),
        "impact": impact,
        "swc_id": swc,
        "description": desc[:500],
        "exploitability_hint": "manual_review",
        "source": item.get("source", tool),
    }


def _dedupe_vulnerabilities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for v in items:
        key = (v.get("category", ""), (v.get("description") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return sorted(out, key=lambda x: -_severity_weight(x.get("severity")))


def _security_score(vulnerabilities: list[dict[str, Any]]) -> int:
    if not vulnerabilities:
        return 0
    return min(100, sum(_severity_weight(v.get("severity")) for v in vulnerabilities))


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
    """Normalize contract source metadata — structured contracts list, framework detection."""
    path, inline = _resolve_path(source_or_path, source_is_code=source_is_code)
    if path is None and inline is None:
        return {"success": False, "error": "path not found and no source provided", "contracts": []}

    text, label = _read_source(path, inline)
    pragmas = _PRAGMA_RE.findall(text)
    contract_details = _parse_contract_details(text)
    imports = _IMPORT_RE.findall(text)
    compiler_version = pragmas[0] if pragmas else None

    return {
        "success": True,
        "source_label": label,
        "path": str(path) if path else None,
        "line_count": len(text.splitlines()),
        "compiler_version": compiler_version,
        "solidity_version_pragmas": pragmas,
        "pragma_versions": pragmas,
        "contracts": contract_details,
        "contract_names": [c["name"] for c in contract_details],
        "import_count": len(imports),
        "imports_sample": imports[:10],
        "uses_openzeppelin_import": bool(_OZ_IMPORT_RE.search(text)),
        "detected_framework": _detect_framework(path),
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
                "impact": "high",
                "description": "Review reentrancy on ETH transfer via .call{value:}",
            }
        )
    if re.search(r"tx\.origin", text):
        swc_matches.append(
            {
                "swc_id": "SWC-115",
                "source": "source_heuristic",
                "check": "tx-origin-usage",
                "impact": "medium",
                "description": "tx.origin used — authentication risk",
            }
        )

    issues: list[dict[str, Any]] = []
    for m in swc_matches:
        swc_id = m.get("swc_id") or "SWC-UNKNOWN"
        issues.append(
            {
                "swc_id": swc_id,
                "title": m.get("check") or swc_id,
                "severity": str(m.get("impact") or "medium").lower(),
                "description": m.get("description") or "",
                "locations": [],
                "exploit_scenario_short": _SWC_EXPLOIT_SCENARIOS.get(
                    swc_id, "Manual review required for exploit preconditions."
                ),
                "source": m.get("source"),
            }
        )

    report_path = DEFAULT_ARTIFACTS / f"{audit_id}-swc.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "success": True,
        "audit_id": audit_id,
        "issues": issues,
        "issue_count": len(issues),
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


def slither_run_detectors(
    path_or_source: str,
    *,
    source_is_code: bool = False,
    excluded_detectors: list[str] | None = None,
) -> dict[str, Any]:
    """Full Slither detector run — spec-shaped detectors[] with locations and swc_refs."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline, err = _prepare_sol_path(path_or_source, source_is_code=source_is_code, audit_id=audit_id)
    if err:
        return err

    excluded = {d.lower() for d in (excluded_detectors or [])}
    toolchain = ContractToolchain()
    payload, result = toolchain.slither_raw_json(path)  # type: ignore[arg-type]

    detectors: list[dict[str, Any]] = []
    if payload and not result.skipped:
        raw = (payload.get("results") or {}).get("detectors", [])
        for det in raw:
            spec = _slither_detector_to_spec(det)
            if spec["id"].lower() in excluded:
                continue
            detectors.append(spec)
    elif not result.skipped:
        for f in result.findings:
            check = f.get("check") or "unknown"
            if check.lower() in excluded:
                continue
            swc = _map_swc_id(check)
            detectors.append(
                {
                    "id": check,
                    "title": check.replace("-", " ").title(),
                    "severity": str(f.get("impact") or "informational").lower(),
                    "description": f.get("description") or "",
                    "locations": [],
                    "swc_refs": [swc] if swc else [],
                }
            )

    return {
        "success": result.ok or result.skipped or bool(detectors),
        "audit_id": audit_id,
        "path": str(path),
        "detectors": detectors,
        "detector_count": len(detectors),
        "findings": result.findings,
        "finding_count": len(detectors),
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
    }


def slither_functions(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """List functions/modifiers — Slither JSON elements or source regex fallback."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline, err = _prepare_sol_path(path_or_source, source_is_code=source_is_code, audit_id=audit_id)
    if err:
        return err

    functions: list[dict[str, Any]] = []
    modifiers: list[str] = []
    text, label = _read_source(path, inline)

    toolchain = ContractToolchain()
    payload, result = toolchain.slither_raw_json(path)  # type: ignore[arg-type]

    if payload and not result.skipped:
        for det in (payload.get("results") or {}).get("detectors", []):
            for el in det.get("elements") or []:
                if el.get("type") == "function":
                    functions.append(
                        {
                            "name": el.get("name"),
                            "type": el.get("type"),
                            "source_mapping": el.get("source_mapping"),
                            "from_detector": det.get("check"),
                        }
                    )
    else:
        for name, vis in _FUNCTION_RE.findall(text):
            functions.append({"name": name, "visibility": vis or "unknown", "source": "regex_fallback"})
        modifiers = _MODIFIER_RE.findall(text)

    return {
        "success": True,
        "audit_id": audit_id,
        "source_label": label,
        "path": str(path),
        "functions": functions,
        "function_count": len(functions),
        "modifiers": modifiers,
        "slither_skipped": result.skipped,
        "slither_skip_reason": result.skip_reason,
    }


def slither_critical_sinks(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """High-impact findings: external calls, transfers, delegatecall, reentrancy."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    slither = run_static_analysis_slither(path_or_source, source_is_code=source_is_code)
    sinks: list[dict[str, Any]] = []
    for f in slither.get("findings") or []:
        check = (f.get("check") or "").lower()
        impact = (f.get("impact") or "").lower()
        if impact in ("high", "critical", "medium") or any(frag in check for frag in _CRITICAL_SINK_FRAGMENTS):
            sinks.append({**f, "sink_type": "critical"})
    return {
        "success": bool(sinks) or slither.get("success") or slither.get("skipped"),
        "audit_id": audit_id,
        "critical_sinks": sinks,
        "sink_count": len(sinks),
        "slither_skipped": slither.get("skipped"),
        "raw_slither_audit_id": slither.get("audit_id"),
    }


def run_aderyn(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Run real Aderyn — skipped if not installed."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline, err = _prepare_sol_path(path_or_source, source_is_code=source_is_code, audit_id=audit_id)
    if err:
        return err
    project_dir = path.parent if path.is_file() else path
    toolchain = ContractToolchain()
    result = toolchain.aderyn_scan(project_dir)
    return _tool_to_mcp(result, audit_id=audit_id, extra={"path": str(path), "project_dir": str(project_dir)})


def list_vulnerabilities(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Aggregated deduplicated list from Slither + SWC + Aderyn + OZ."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    slither = run_static_analysis_slither(path_or_source, source_is_code=source_is_code)
    swc = check_swc_patterns(path_or_source, source_is_code=source_is_code)
    aderyn = run_aderyn(path_or_source, source_is_code=source_is_code)
    oz = check_openzeppelin_rules(path_or_source, source_is_code=source_is_code)

    vulns: list[dict[str, Any]] = []
    for f in slither.get("findings") or []:
        vulns.append(_normalize_vulnerability(f, tool="slither"))
    for m in swc.get("swc_matches") or []:
        vulns.append(
            _normalize_vulnerability(
                {
                    "check": m.get("check") or m.get("swc_id"),
                    "impact": m.get("impact") or "medium",
                    "description": m.get("description"),
                    "swc_id": m.get("swc_id"),
                    "source": m.get("source"),
                },
                tool="swc",
            )
        )
    for f in aderyn.get("findings") or []:
        vulns.append(_normalize_vulnerability({**f, "impact": "medium"}, tool="aderyn"))
    for n in oz.get("notes") or []:
        vulns.append(
            _normalize_vulnerability(
                {
                    "check": n.get("rule"),
                    "impact": n.get("severity"),
                    "description": n.get("message"),
                    "source": "openzeppelin_heuristic",
                },
                tool="openzeppelin",
            )
        )

    deduped = _dedupe_vulnerabilities(vulns)
    report_path = DEFAULT_ARTIFACTS / f"{audit_id}-vulnerabilities.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "success": True,
        "audit_id": audit_id,
        "vulnerabilities": deduped,
        "vulnerability_count": len(deduped),
        "security_score": _security_score(deduped),
        "sources": {"slither_skipped": slither.get("skipped"), "aderyn_skipped": aderyn.get("skipped")},
        "raw_report_path": str(report_path),
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def scan_contract(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Aggregated scan: parse + deduped vulnerabilities + security_score + critical sinks."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    parsed = parse_contract(path_or_source, source_is_code=source_is_code)
    vulns = list_vulnerabilities(path_or_source, source_is_code=source_is_code)
    sinks = slither_critical_sinks(path_or_source, source_is_code=source_is_code)

    report = {
        "success": parsed.get("success", False),
        "audit_id": audit_id,
        "parse": parsed,
        "vulnerabilities": vulns.get("vulnerabilities", []),
        "vulnerability_count": vulns.get("vulnerability_count", 0),
        "security_score": vulns.get("security_score", 0),
        "critical_sinks": sinks.get("critical_sinks", []),
        "critical_sink_count": sinks.get("sink_count", 0),
        "raw_report_path": vulns.get("raw_report_path"),
    }
    out_path = DEFAULT_ARTIFACTS / f"{audit_id}-scan.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["scan_report_path"] = str(out_path)
    return report


def full_audit(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Deep pipeline: parse → slither → swc → aderyn → oz → aggregated list."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    parsed = parse_contract(path_or_source, source_is_code=source_is_code)
    slither = run_static_analysis_slither(path_or_source, source_is_code=source_is_code)
    swc = check_swc_patterns(path_or_source, source_is_code=source_is_code)
    aderyn = run_aderyn(path_or_source, source_is_code=source_is_code)
    oz = check_openzeppelin_rules(path_or_source, source_is_code=source_is_code)
    vulns = list_vulnerabilities(path_or_source, source_is_code=source_is_code)

    report = {
        "success": parsed.get("success", False),
        "audit_id": audit_id,
        "parse": parsed,
        "slither": slither,
        "swc": swc,
        "aderyn": aderyn,
        "openzeppelin": oz,
        "aggregated": vulns,
        "total_findings": vulns.get("vulnerability_count", 0),
        "security_score": vulns.get("security_score", 0),
    }
    report_path = DEFAULT_ARTIFACTS / f"{audit_id}-full.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["raw_report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def slither_structure(path_or_source: str, *, source_is_code: bool = False) -> dict[str, Any]:
    """Extract contract structure: state vars, call graph hints, external entry points."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline, err = _prepare_sol_path(path_or_source, source_is_code=source_is_code, audit_id=audit_id)
    if err:
        return err

    text, label = _read_source(path, inline)
    parsed = _parse_contract_details(text)
    libraries = _LIBRARY_RE.findall(text)
    contracts_out: list[dict[str, Any]] = []

    for c in parsed:
        block_match = re.search(rf"\bcontract\s+{re.escape(c['name'])}\s*[^{{]*\{{", text, re.I)
        block = ""
        if block_match:
            start = block_match.end()
            depth = 1
            i = start
            while i < len(text) and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            block = text[start : i - 1]

        state_variables: list[dict[str, Any]] = []
        for sv in _STATE_VAR_RE.finditer(block):
            state_variables.append(
                {
                    "type": sv.group(4),
                    "name": sv.group(5),
                    "visibility": "public" if "public" in sv.group(0) else "internal",
                    "constant": bool(sv.group(1)),
                    "immutable": bool(sv.group(2)),
                }
            )
        contracts_out.append(
            {
                "name": c["name"],
                "base_contracts": c.get("inheritance", []),
                "uses_libraries": libraries,
                "state_variables": state_variables,
            }
        )

    call_graph: list[dict[str, str]] = []
    fn_names = {f for c in parsed for f in c.get("public_functions", []) + c.get("external_functions", [])}
    for fn in fn_names:
        fn_block_match = re.search(rf"function\s+{re.escape(fn)}\s*\([^{{]*\{{", text, re.I)
        if not fn_block_match:
            continue
        start = fn_block_match.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start : i - 1]
        for callee in set(_CALL_RE.findall(body)):
            if callee in fn_names and callee != fn:
                call_graph.append({"caller": fn, "callee": callee, "type": "internal"})

    external_entry_points = [
        {"contract": c["name"], "function": fn, "visibility": "external"}
        for c in parsed
        for fn in c.get("external_functions", [])
    ] + [
        {"contract": c["name"], "function": fn, "visibility": "public"}
        for c in parsed
        for fn in c.get("public_functions", [])
    ]

    return {
        "success": True,
        "audit_id": audit_id,
        "source_label": label,
        "path": str(path),
        "contracts": contracts_out,
        "call_graph": call_graph,
        "external_entry_points": external_entry_points,
    }


def aderyn_analyze(
    path_or_source: str,
    *,
    source_is_code: bool = False,
    ruleset: str = "default",
) -> dict[str, Any]:
    """Run Aderyn and map findings to violations[] with property/status."""
    raw = run_aderyn(path_or_source, source_is_code=source_is_code)
    violations: list[dict[str, Any]] = []
    if raw.get("skipped"):
        return {
            **raw,
            "ruleset": ruleset,
            "violations": [],
            "violation_count": 0,
        }
    for idx, f in enumerate(raw.get("findings") or []):
        title = f.get("title") or f.get("check") or f"aderyn-rule-{idx}"
        violations.append(
            {
                "rule_id": title.lower().replace(" ", "-"),
                "property": title,
                "status": "violated",
                "details": f.get("description") or f.get("source") or "See Aderyn report",
            }
        )
    if not violations and raw.get("success"):
        violations.append(
            {
                "rule_id": "aderyn-clean",
                "property": "no violations reported",
                "status": "satisfied",
                "details": "Aderyn completed without flagged issues in parsed output",
            }
        )
    return {
        **raw,
        "ruleset": ruleset,
        "violations": violations,
        "violation_count": len([v for v in violations if v["status"] == "violated"]),
    }


def mythril_scan_summary(
    *,
    bytecode: str | None = None,
    address: str | None = None,
    chain: str = "ethereum",
    path_or_source: str | None = None,
    source_is_code: bool = False,
) -> dict[str, Any]:
    """Light Mythril summary from bytecode, on-chain address, or source file."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    toolchain = ContractToolchain()
    result: ToolResult | None = None

    if address:
        onchain = fetch_onchain_data(address, chain=chain)
        if not onchain.get("success") or not onchain.get("is_contract"):
            return {
                "success": False,
                "audit_id": audit_id,
                "error": "address has no contract bytecode",
                "issues": [],
            }
        code_hex = "0x"
        try:
            client = StealthRpcClient(RPC_CONFIG)
            _, resp = client.call("eth_getCode", [address.strip().lower(), "latest"], timeout=12.0)
            code_hex = resp.get("result") or "0x"
        except Exception:
            code_hex = "0x"
        result = toolchain.mythril_analyze_bytecode(code_hex)
    elif bytecode:
        result = toolchain.mythril_analyze_bytecode(bytecode)
    elif path_or_source:
        myth = run_bytecode_scan_mythril(path_or_source, source_is_code=source_is_code)
        issues = [
            {
                "type": (f.get("title") or f.get("check") or "unknown").lower().replace(" ", "-"),
                "severity": f.get("severity") or f.get("impact") or "unknown",
                "description": f.get("description") or "",
                "exploitability_estimate": "manual_review",
            }
            for f in (myth.get("findings") or [])
        ]
        return {
            **myth,
            "audit_id": audit_id,
            "issues": issues,
            "issue_count": len(issues),
        }
    else:
        return {"success": False, "audit_id": audit_id, "error": "provide bytecode, address, or path", "issues": []}

    assert result is not None
    issues: list[dict[str, Any]] = []
    for f in result.findings:
        sev = str(f.get("severity") or "medium").lower()
        exploitability = "low"
        if sev in ("high", "critical"):
            exploitability = "likely"
        issues.append(
            {
                "type": (f.get("title") or "unknown").lower().replace(" ", "-"),
                "severity": sev,
                "description": f.get("description") or "",
                "exploitability_estimate": exploitability,
                "swc_id": f.get("swc_id"),
            }
        )
    return {
        "success": result.ok or result.skipped,
        "audit_id": audit_id,
        "issues": issues,
        "issue_count": len(issues),
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
        "read_only": bool(address),
    }


def contract_security_score(
    path_or_source: str,
    *,
    source_is_code: bool = False,
    include_mythril: bool = False,
) -> dict[str, Any]:
    """Aggregated triage score (100 = best) with grade and top risks."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    slither = slither_run_detectors(path_or_source, source_is_code=source_is_code)
    swc = check_swc_patterns(path_or_source, source_is_code=source_is_code)
    normalized = normalize_findings(
        {
            "slither": slither.get("detectors") or [],
            "swc": swc.get("issues") or [],
        }
    )
    deduped = normalized.get("deduped_findings") or []
    metrics = _count_by_severity(deduped)
    risk_points = min(
        100,
        metrics["critical"] * 25 + metrics["high"] * 15 + metrics["medium"] * 8 + metrics["low"] * 3,
    )
    score = max(0, 100 - risk_points)
    top_risks = [
        {
            "id": f.get("id"),
            "category": f.get("category"),
            "severity": f.get("severity"),
            "description": (f.get("description") or "")[:200],
            "sources": f.get("sources"),
        }
        for f in deduped[:5]
    ]

    mythril_block: dict[str, Any] | None = None
    if include_mythril:
        mythril_block = mythril_scan_summary(path_or_source=path_or_source, source_is_code=source_is_code)

    return {
        "success": True,
        "audit_id": audit_id,
        "score": score,
        "grade": _risk_grade(score),
        "metrics": metrics,
        "top_risks": top_risks,
        "slither_skipped": slither.get("skipped"),
        "mythril": mythril_block,
    }


def onchain_metadata(address: str, chain: str = "ethereum") -> dict[str, Any]:
    """Read-only on-chain metadata: proxy hints, bytecode, verification status unknown without explorer."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    addr = address.strip().lower()
    if not re.match(r"^0x[0-9a-f]{40}$", addr):
        return {"success": False, "error": "invalid address", "audit_id": audit_id}

    base = fetch_onchain_data(addr, chain=chain)
    if not base.get("success"):
        return {**base, "audit_id": audit_id}

    implementation_address: str | None = None
    is_proxy = False
    try:
        client = StealthRpcClient(RPC_CONFIG)
        _, storage = client.call("eth_getStorageAt", [addr, _EIP1967_IMPL_SLOT, "latest"], timeout=12.0)
        slot_val = storage.get("result") or "0x" + "0" * 64
        if slot_val and int(slot_val, 16) != 0:
            is_proxy = True
            implementation_address = "0x" + slot_val[-40:]
    except Exception:
        pass

    return {
        "success": True,
        "audit_id": audit_id,
        "address": addr,
        "chain": chain,
        "is_contract": base.get("is_contract"),
        "bytecode_length": base.get("bytecode_length"),
        "is_proxy": is_proxy,
        "implementation_address": implementation_address,
        "deployer": None,
        "txn_history_summary": {
            "note": "Full deploy/upgrade history requires block explorer API (read-only RPC only here)",
        },
        "verified_source": {
            "available": False,
            "note": "Use explorer MCP/API to confirm verified source matches audited code",
        },
        "read_only": True,
    }


def compile_and_abi(path_or_source: str, *, contract_name: str | None = None) -> dict[str, Any]:
    """Compile Foundry project and return ABI/bytecode artifacts."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    path, inline = _resolve_path(path_or_source, source_is_code=False)
    if path is None:
        return {
            "success": False,
            "audit_id": audit_id,
            "error": "compile_and_abi requires a project or file path",
        }
    project_dir = path.parent if path.is_file() else path
    toolchain = ContractToolchain()
    result = toolchain.forge_compile_abi(project_dir, contract_name=contract_name)
    if result.skipped:
        return {
            "success": False,
            "audit_id": audit_id,
            "skipped": True,
            "skip_reason": result.skip_reason,
            "abi": None,
            "bytecode": None,
            "deployed_bytecode": None,
        }
    artifact = (result.findings or [{}])[0] if result.findings else {}
    return {
        "success": result.ok,
        "audit_id": audit_id,
        "contract_name": artifact.get("contract_name") or contract_name,
        "abi": artifact.get("abi"),
        "bytecode": artifact.get("bytecode"),
        "deployed_bytecode": artifact.get("deployed_bytecode"),
        "artifact_path": artifact.get("artifact_path"),
        "artifacts": result.findings,
        "error": result.error,
    }


def generate_audit_report_skeleton(contract_name: str, purpose: str = "token") -> dict[str, Any]:
    """Return standardized audit report section skeleton for agent fill-in."""
    purpose = purpose.lower()
    security_model_notes = {
        "governance": "Document admin keys, timelocks, proposal thresholds, and upgrade paths.",
        "token": "Document mint/burn roles, pausing, blacklist, and fee mechanics.",
        "staking": "Document reward rate, withdrawal delays, slashing, and oracle trust.",
        "defi": "Document oracle sources, liquidation, collateral factors, and external call trust.",
    }
    return {
        "success": True,
        "contract_name": contract_name,
        "purpose": purpose,
        "sections": {
            "summary": {
                "title": "Executive Summary",
                "fields": ["scope", "methodology", "overall_grade", "critical_count"],
            },
            "security_model": {
                "title": "Security Model & Trust Assumptions",
                "prompt": security_model_notes.get(purpose, "Document roles, privileges, and invariants."),
            },
            "findings": {
                "title": "Findings",
                "row_schema": ["id", "severity", "category", "swc_id", "location", "description", "recommendation"],
            },
            "recommendations": {
                "title": "Recommendations",
                "groups": ["critical_fixes", "defense_in_depth", "monitoring"],
            },
            "risk_matrix": {
                "title": "Risk Matrix",
                "axes": {"likelihood": ["low", "medium", "high"], "impact": ["low", "medium", "high", "critical"]},
            },
        },
    }


def normalize_findings(raw_findings: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Merge and dedupe findings from multiple analyzer outputs."""
    audit_id = f"audit-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    collected: list[dict[str, Any]] = []

    if isinstance(raw_findings, list):
        buckets = {"items": raw_findings}
    else:
        buckets = raw_findings

    for source, items in buckets.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            label = item.get("id") or item.get("check") or item.get("title") or item.get("swc_id") or "unknown"
            sev = str(item.get("severity") or item.get("impact") or "info").lower()
            desc = item.get("description") or item.get("details") or ""
            locs = item.get("locations") or []
            if not locs and item.get("source"):
                locs = [{"source": item.get("source")}]
            collected.append(
                {
                    "id": f"{source}:{label}",
                    "category": _infer_finding_category(str(label)),
                    "severity": sev,
                    "description": desc,
                    "sources": [source],
                    "locations": locs,
                    "swc_id": (item.get("swc_refs") or [None])[0] if item.get("swc_refs") else item.get("swc_id"),
                }
            )

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for f in collected:
        key = (f.get("category", ""), (f.get("description") or "")[:120])
        if key in merged:
            merged[key]["sources"] = sorted(set(merged[key]["sources"] + f["sources"]))
            if f.get("locations"):
                merged[key]["locations"].extend(f["locations"])
        else:
            merged[key] = {**f, "locations": list(f.get("locations") or [])}

    deduped = sorted(merged.values(), key=lambda x: -_severity_weight(x.get("severity")))
    return {
        "success": True,
        "audit_id": audit_id,
        "deduped_findings": deduped,
        "finding_count": len(deduped),
    }
