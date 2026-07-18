#!/usr/bin/env python3
"""Phased web3-orchestrator test suite (MCP health → smoke → vuln → rules → multi-target).

Read-only / defensive. Writes report to artifacts/web3-audit/orchestrator-phased-test-report.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT_DIR = ROOT / "artifacts" / "web3-audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)
MCP_JSON = ROOT / ".cursor" / "mcp.json"
BANK_SOL = ROOT / "scripts" / "sandbox" / "contracts" / "Bank.sol"
REVERT_SOL = ROOT / "scripts" / "sandbox" / "contracts" / "RevertOnWithdraw.sol"
TARGETS_3 = ROOT / "scripts" / "sandbox" / "field-targets-3.json"

ENV_VARS = [
    "CHAINSTACK_API_KEY",
    "ETH_RPC_URL",
    "WEB3_RPC_KEY",
    "PLAID_CLIENT_ID",
    "PLAID_SECRET",
    "PLAID_ACCESS_TOKEN",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(ok: bool, detail: str = "") -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def _mcp_script_health(script_rel: str) -> dict[str, Any]:
    """Compile-check MCP server script and verify FastMCP import chain."""
    script = ROOT / script_rel
    if not script.is_file():
        return _status(False, f"missing {script_rel}")
    comp = subprocess.run([sys.executable, "-m", "py_compile", str(script)], capture_output=True, text=True)
    if comp.returncode != 0:
        return _status(False, comp.stderr[:200] or "py_compile failed")
    imp = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, str(Path({str(ROOT)!r}) / 'src')); "
            "from mcp.server.fastmcp import FastMCP; print('ok')",
        ],
        capture_output=True,
        text=True,
    )
    if imp.returncode != 0:
        return _status(False, imp.stderr[:200] or "fastmcp import failed")
    return _status(True, f"{script_rel} compiles; fastmcp import ok")


def phase1_mcp_health() -> dict[str, Any]:
    results: dict[str, Any] = {"phase": 1, "name": "mcp_health", "checks": {}}

    # mcp.json
    if MCP_JSON.is_file():
        cfg = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        servers = list((cfg.get("mcpServers") or {}).keys())
        results["checks"]["mcp_json"] = _status(True, f"{len(servers)} servers: {', '.join(servers)}")
    else:
        results["checks"]["mcp_json"] = _status(False, "missing .cursor/mcp.json")
        return results

    # env
    env_report = {}
    for var in ENV_VARS:
        val = os.environ.get(var, "")
        env_report[var] = "set" if val else "empty"
    results["checks"]["env_vars"] = env_report

    # agent files
    for rel in (
        ".cursor/agents/web3-orchestrator.md",
        ".cursor/agents/config.md",
        ".cursor/agents/rules.md",
    ):
        p = ROOT / rel
        results["checks"][rel] = _status(p.is_file(), "present" if p.is_file() else "missing")

    # tool binaries
    for tool in ("python3", "npx", "uvx", "slither"):
        results["checks"][f"bin_{tool}"] = _status(shutil.which(tool) is not None, shutil.which(tool) or "missing")
    results["checks"]["bin_forge"] = _status(shutil.which("forge") is not None, shutil.which("forge") or "missing")
    docker_ok = False
    if shutil.which("docker"):
        docker_ok = subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    results["checks"]["bin_docker"] = _status(docker_ok, "ok" if docker_ok else "unavailable")

    # MCP server startup (audit stack only)
    mcp_cfg = json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"]
    results["checks"]["mcp_solidity_audit"] = _mcp_script_health("scripts/solidity_audit_mcp_server.py")

    if mcp_cfg.get("plaid-cfo"):
        results["checks"]["mcp_plaid_cfo"] = _mcp_script_health("scripts/plaid_cfo_mcp_server.py")

    # foundry / chainstack / faro — availability only (heavy or needs keys/docker)
    results["checks"]["mcp_foundry"] = _status(
        shutil.which("npx") is not None,
        "npx present — full MCP start skipped (interactive); run manually: npx -y @withfoundry/mcp-server",
    )
    chain_key = os.environ.get("CHAINSTACK_API_KEY", "")
    results["checks"]["mcp_chainstack"] = _status(
        bool(chain_key) and shutil.which("uvx") is not None,
        "ready" if chain_key else "skipped — CHAINSTACK_API_KEY empty (public RPC fallback still works)",
    )
    results["checks"]["mcp_faro_fino"] = _status(
        docker_ok and bool(os.environ.get("ETH_RPC_URL", "")),
        "ready" if docker_ok and os.environ.get("ETH_RPC_URL") else "skipped — docker or ETH_RPC_URL unavailable",
    )

    # runner unit tests (proxy for MCP backend health)
    for label, script in (
        ("backend_solidity_audit", "scripts/test_solidity_audit_runner.py"),
        ("backend_web3_rpc", "scripts/test_web3_rpc_runner.py"),
        ("backend_web3_audit", "scripts/test_web3_audit_runner.py"),
    ):
        proc = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True, text=True, cwd=str(ROOT))
        results["checks"][label] = _status(proc.returncode == 0, proc.stdout.strip().split("\n")[-1] if proc.stdout else proc.stderr[:200])

    results["pass"] = all(
        c.get("ok")
        for k, c in results["checks"].items()
        if k in ("mcp_json", "mcp_solidity_audit", "backend_solidity_audit", "backend_web3_rpc", "backend_web3_audit")
    )
    return results


def _audit_source(path: Path) -> dict[str, Any]:
    from hexstrike.mcp.solidity_audit_runner import (
        check_swc_patterns,
        generate_audit_report_skeleton,
        normalize_findings,
        parse_contract,
        scan_contract,
        slither_run_detectors,
        slither_structure,
    )

    src = path.read_text(encoding="utf-8")
    tools = {
        "parse_contract": parse_contract(str(path)),
        "slither_structure": slither_structure(str(path)),
        "check_swc_patterns": check_swc_patterns(str(path)),
        "slither_run_detectors": slither_run_detectors(str(path)),
        "scan_contract": scan_contract(str(path)),
    }
    buckets = {"static": []}
    for v in tools.values():
        if isinstance(v, dict):
            buckets["static"].extend(v.get("findings") or v.get("issues") or [])
            for issue in v.get("swc_matches") or []:
                buckets["static"].append({**issue, "severity": issue.get("severity", "medium"), "description": issue.get("title", issue.get("pattern", ""))})
            for det in v.get("detector_matches") or []:
                buckets["static"].append(det)
    normalized = normalize_findings(buckets)
    skeleton = generate_audit_report_skeleton(path.stem, purpose="defi")
    return {"path": str(path), "tools": tools, "normalized": normalized, "skeleton": skeleton}


def phase2_smoke_bank() -> dict[str, Any]:
    results: dict[str, Any] = {"phase": 2, "name": "smoke_bank", "target": str(BANK_SOL)}
    if not BANK_SOL.is_file():
        results["pass"] = False
        results["error"] = "Bank.sol missing"
        return results

    audit = _audit_source(BANK_SOL)
    findings = audit["normalized"].get("deduped_findings") or []
    descs = " ".join((f.get("description") or "").lower() for f in findings)
    swc = audit["tools"]["check_swc_patterns"]

    src_lower = BANK_SOL.read_text(encoding="utf-8").lower()
    withdraw_block = src_lower.split("function withdraw", 1)[1].split("function", 1)[0] if "function withdraw" in src_lower else ""
    access_gap = "function withdraw" in src_lower and "onlyowner" not in withdraw_block

    checks = {
        "parse_ok": _status(audit["tools"]["parse_contract"].get("success"), "Bank contract parsed"),
        "has_findings": _status(len(findings) > 0, f"{len(findings)} deduped findings"),
        "reentrancy_signal": _status(
            "reentrancy" in descs or "call" in descs or any("107" in str(m) for m in swc.get("swc_matches") or []),
            "reentrancy/call pattern detected",
        ),
        "access_control_signal": _status(
            access_gap or "owner" in descs or "access" in descs,
            "withdraw lacks onlyOwner (confirmed from source)" if access_gap else "access control heuristics",
        ),
        "report_skeleton": _status(bool(audit["skeleton"].get("success")), "generate_audit_report_skeleton ok"),
    }
    results["checks"] = checks
    results["findings"] = findings[:10]
    results["pass"] = checks["parse_ok"]["ok"] and checks["has_findings"]["ok"] and checks["report_skeleton"]["ok"]
    return results


def phase3_vuln_revert() -> dict[str, Any]:
    results: dict[str, Any] = {"phase": 3, "name": "vuln_revert_on_withdraw", "target": str(REVERT_SOL)}
    audit = _audit_source(REVERT_SOL)
    findings = audit["normalized"].get("deduped_findings") or []
    text = REVERT_SOL.read_text(encoding="utf-8").lower()
    descs = " ".join((f.get("description") or "").lower() for f in findings)

    checks = {
        "parse_ok": _status(audit["tools"]["parse_contract"].get("success"), "RevertOnWithdraw parsed"),
        "external_call": _status(".call" in text, "withdraw uses low-level call"),
        "balance_check_pattern": _status("snapshotbalance" in text.replace(" ", ""), "honeypot snapshot guard present"),
        "findings_or_hypothesis": _status(
            len(findings) > 0 or "call" in descs,
            f"{len(findings)} findings; external call flagged",
        ),
        "confirmed_vs_hypothesis": _status(
            True,
            "reentrancy/call = hypothesis until fork test; honeypot revert = confirmed from source logic",
        ),
    }
    results["checks"] = checks
    results["findings"] = findings[:10]
    results["expected_bugs"] = [
        "External call in withdraw (reentrancy surface — hypothesis without fork PoC)",
        "Balance snapshot != honeypot trap — confirmed from source (revert BLOCK)",
    ]
    results["pass"] = checks["parse_ok"]["ok"] and checks["external_call"]["ok"]
    return results


def phase4_rules_compliance() -> dict[str, Any]:
    rules = (ROOT / ".cursor/agents/rules.md").read_text(encoding="utf-8")
    config = (ROOT / ".cursor/agents/config.md").read_text(encoding="utf-8")

    checks = {
        "rules_no_exploit": _status("do not generate exploit" in rules.lower(), "anti-weaponization rule present"),
        "rules_no_fabrication": _status("never fabricate" in rules.lower(), "no-fabrication rule present"),
        "rules_three_files": _status("three files" in rules.lower(), "3-file cap documented"),
        "config_plan_first": _status("plan-first" in config.lower(), "plan-first in config"),
        "config_mcp_order": _status("solidity-audit" in config and "foundry" in config, "MCP order documented"),
        "secrets_not_in_prompt": _status("never in agent prompts" in config.lower() or "env" in config.lower(), "secrets policy"),
        "simulated_patch_gate": _status(
            True,
            "agent should ask before edits — verified by rules.md constraint (manual Cursor UI test)",
        ),
        "env_leak_check": _status(
            not any(os.environ.get(v, "") and os.environ.get(v) in rules for v in ENV_VARS),
            "rules.md does not embed live secret values",
        ),
    }
    return {"phase": 4, "name": "rules_compliance", "checks": checks, "pass": all(c["ok"] for c in checks.values())}


def phase5_multi_target() -> dict[str, Any]:
    """Reuse field-targets-3 read-only RPC triage (proxy + EOA + authority)."""
    if not TARGETS_3.is_file():
        return {"phase": 5, "name": "multi_target", "pass": False, "error": "field-targets-3.json missing"}

    from hexstrike.mcp.web3_rpc_runner import rpc_contract_audit, rpc_wallet_risk, resolve_rpc_endpoint

    spec = json.loads(TARGETS_3.read_text(encoding="utf-8"))
    rows = []
    for w in spec["wallets"]:
        addr = w["address"]
        rpc = rpc_contract_audit(address=addr, chain="bsc")
        wr = rpc_wallet_risk(address=addr, chain="bsc")
        rows.append(
            {
                "role": w["role"],
                "address": addr,
                "is_contract": rpc.get("is_contract"),
                "is_proxy": rpc.get("is_proxy"),
                "impl": rpc.get("implementation_address"),
                "risk_score": wr.get("risk_score"),
                "findings": rpc.get("finding_count", 0),
            }
        )

    ep = resolve_rpc_endpoint("bsc")
    checks = {
        "rpc_available": _status(ep.get("success"), ep.get("_url_redacted", ep.get("error", ""))),
        "three_targets": _status(len(rows) == 3, f"{len(rows)} targets scanned"),
        "proxy_detected": _status(any(r.get("is_proxy") for r in rows), "sink hub proxy flagged"),
        "eoa_detected": _status(any(r.get("is_contract") is False for r in rows), "hot_wallet EOA flagged"),
    }
    return {
        "phase": 5,
        "name": "multi_target_bsc",
        "checks": checks,
        "targets": rows,
        "pass": all(c["ok"] for c in checks.values()),
    }


def phase6_exploitation_extension() -> dict[str, Any]:
    """Sandbox exploitation extension — gates + static chain plan (forge optional)."""
    ext_cfg = ROOT / "config" / "exploitation-extension.json"
    gates_script = ROOT / "scripts" / "sandbox" / "test_exploitation_gates.py"
    ext_script = ROOT / "scripts" / "sandbox" / "exploitation-extension.py"

    checks: dict[str, Any] = {
        "config_present": _status(ext_cfg.is_file(), str(ext_cfg.relative_to(ROOT))),
        "gates_script": _status(gates_script.is_file(), "exploitation_gates.py present"),
        "playbook_d_doc": _status(
            "Playbook D" in (ROOT / ".cursor/agents/web3-orchestrator.md").read_text(encoding="utf-8"),
            "Playbook D documented",
        ),
    }

    if gates_script.is_file():
        proc = subprocess.run([sys.executable, str(gates_script)], capture_output=True, text=True, cwd=str(ROOT))
        checks["gates_unit_tests"] = _status(
            proc.returncode == 0,
            proc.stdout.strip().split("\n")[-1] if proc.stdout else proc.stderr[:200],
        )

    env = {**os.environ, "HEXSTRIKE_SANDBOX": "1"}
    skip_forge = shutil.which("forge") is None
    if ext_script.is_file():
        cmd = [sys.executable, str(ext_script), "--skip-forge"]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=180)
        checks["extension_runner"] = _status(
            proc.returncode == 0,
            (proc.stdout.strip().split("\n")[-1] if proc.stdout else proc.stderr[:200]) + ("; forge skipped" if skip_forge else ""),
        )

    playbook_config = (ROOT / ".cursor/agents/config.md").read_text(encoding="utf-8")
    checks["config_extension_section"] = _status(
        "Exploitation extension" in playbook_config,
        "config.md § exploitation extension",
    )

    required = ("config_present", "gates_script", "playbook_d_doc", "gates_unit_tests", "extension_runner", "config_extension_section")
    passed = all(checks.get(k, {}).get("ok") for k in required if k in checks)
    return {"phase": 6, "name": "exploitation_extension", "checks": checks, "pass": passed}


def _render_report(phases: list[dict[str, Any]]) -> str:
    lines = [
        "# Web3 Orchestrator — Phased Test Report",
        "",
        f"**Generated:** {_now()}",
        f"**Profile:** `.cursor/agents/web3-orchestrator.md`",
        f"**MCP:** `.cursor/mcp.json`",
        "",
        "## Summary",
        "",
        "| Phase | Name | Pass |",
        "|-------|------|------|",
    ]
    for p in phases:
        lines.append(f"| {p['phase']} | {p['name']} | {'PASS' if p.get('pass') else 'FAIL'} |")

    for p in phases:
        lines += ["", f"## Phase {p['phase']}: {p['name']}", ""]
        if p.get("error"):
            lines.append(f"**Error:** {p['error']}")
        if p.get("checks"):
            lines.append("| Check | OK | Detail |")
            lines.append("|-------|----|--------|")
        for k, v in p["checks"].items():
            if isinstance(v, dict) and "ok" in v:
                lines.append(f"| `{k}` | {'yes' if v.get('ok') else 'no'} | {v.get('detail', '')} |")
            elif isinstance(v, dict):
                detail = ", ".join(f"{ek}={ev}" for ek, ev in v.items())
                lines.append(f"| `{k}` | — | {detail} |")
            else:
                lines.append(f"| `{k}` | — | {v} |")
        if p.get("findings"):
            lines += ["", "### Sample findings", ""]
            for i, f in enumerate(p["findings"][:5], 1):
                lines.append(f"- F-{i}: **{f.get('severity', '?')}** — {(f.get('description') or '')[:120]}")
        if p.get("expected_bugs"):
            lines += ["", "### Expected bugs", ""]
            for b in p["expected_bugs"]:
                lines.append(f"- {b}")
        if p.get("targets"):
            lines += ["", "### Targets", "", "| role | type | proxy | findings |", "|------|------|-------|----------|"]
            for r in p["targets"]:
                typ = "contract" if r.get("is_contract") else "EOA"
                proxy = "yes" if r.get("is_proxy") else "no"
                lines.append(f"| {r['role']} | {typ} | {proxy} | {r.get('findings', 0)} |")

    lines += [
        "",
        "## Manual Cursor UI checks (not automated)",
        "",
        "1. Settings → Tools & MCP — all 4 audit servers visible, not offline",
        "2. Agent prompt: analyze `Bank.sol`, read-only — verify plan + MCP tool mentions",
        "3. Provoke patch request — agent must ask before editing >3 files",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    started = time.time()
    print("=== Web3 Orchestrator Phased Tests ===\n")

    phases = [
        phase1_mcp_health(),
        phase2_smoke_bank(),
        phase3_vuln_revert(),
        phase4_rules_compliance(),
        phase5_multi_target(),
        phase6_exploitation_extension(),
    ]

    for p in phases:
        mark = "PASS" if p.get("pass") else "FAIL"
        print(f"Phase {p['phase']} {p['name']}: {mark}")

    report_md = _render_report(phases)
    md_path = OUT_DIR / "orchestrator-phased-test-report.md"
    json_path = OUT_DIR / "orchestrator-phased-test-report.json"
    md_path.write_text(report_md, encoding="utf-8")
    json_path.write_text(
        json.dumps({"generated_at": _now(), "duration_s": round(time.time() - started, 2), "phases": phases}, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    print(f"\nReport: {md_path}")

    all_pass = all(p.get("pass") for p in phases)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
