#!/usr/bin/env python3
"""Full test-celi run: target pool ingest → web3-orchestrator MCP audit on all targets."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TARGETS_FILE = ROOT / "scripts/sandbox/field-targets-3.json"
POOL_ROOT = ROOT / "data/pentest/targets"
OUT = ROOT / "artifacts/target-pool"
OUT.mkdir(parents=True, exist_ok=True)

CHAIN = "bsc"


def _run_ingest() -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ingest-target-pool.py"), "--root", str(POOL_ROOT), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    data = json.loads(proc.stdout) if proc.returncode == 0 else {"success": False, "stderr": proc.stderr}
    (OUT / "ingested-lite.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _audit_target(wallet: dict) -> dict:
    from hexstrike.mcp.web3_audit_providers import goplus_contract_risk, forta_get_alerts
    from hexstrike.mcp.solidity_audit_runner import onchain_metadata, normalize_findings
    from hexstrike.mcp.web3_rpc_runner import rpc_contract_audit, rpc_wallet_risk, rpc_event_intel, resolve_rpc_endpoint, _rpc_call

    addr = wallet["address"]
    impl_hint = (wallet.get("context") or {}).get("implementation")

    endpoint = resolve_rpc_endpoint(CHAIN)
    from_block = "0x0"
    if endpoint.get("success"):
        br = _rpc_call(endpoint["_url"], "eth_blockNumber", [])
        if br.get("success"):
            from_block = hex(max(0, int(br["result"], 16) - 100_000))

    tools = {
        "onchain_metadata": onchain_metadata(address=addr, chain=CHAIN),
        "rpc_contract_audit": rpc_contract_audit(address=addr, chain=CHAIN),
        "rpc_wallet_risk": rpc_wallet_risk(address=addr, chain=CHAIN),
        "goplus": goplus_contract_risk(address=addr, chain=CHAIN),
        "forta": forta_get_alerts(address=addr, chain=CHAIN),
        "event_intel": rpc_event_intel(addr, chain=CHAIN, from_block=from_block, to_block="latest"),
    }

    impl = tools["rpc_contract_audit"].get("implementation_address") or impl_hint
    if impl and impl.lower() != addr.lower():
        tools["implementation"] = {
            "address": impl,
            "rpc_contract_audit": rpc_contract_audit(address=impl, chain=CHAIN),
            "goplus": goplus_contract_risk(address=impl, chain=CHAIN),
            "onchain_metadata": onchain_metadata(address=impl, chain=CHAIN),
        }

    findings = []
    for v in tools.values():
        if isinstance(v, dict):
            findings.extend(v.get("findings") or [])
    if isinstance(tools.get("implementation"), dict):
        for v in tools["implementation"].values():
            if isinstance(v, dict):
                for f in v.get("findings") or []:
                    findings.append({**f, "description": f"[impl] {f.get('description','')}"})

    return {
        "role": wallet["role"],
        "address": addr,
        "chain": wallet.get("chain", "BSC"),
        "labels": wallet.get("labels"),
        "context": wallet.get("context"),
        "tools": tools,
        "raw_finding_count": len(findings),
        "_findings": findings,
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print("=== TEST ЦЕЛИ — full run (3 BSC targets) ===\n")

    print("[1/4] Target pool ingest (lite)...")
    ingest = _run_ingest()
    print(f"  files={ingest.get('file_count')} web3={len((ingest.get('indicators') or {}).get('web3', []))}")

    print("[2/4] Load field-targets-3...")
    spec = json.loads(TARGETS_FILE.read_text())
    wallets = spec["wallets"]
    print(f"  targets={len(wallets)}")

    print("[3/4] Web3 orchestrator MCP audit (per target)...")
    audits = []
    buckets = {}
    for w in wallets:
        print(f"  → {w['role']} {w['address']}")
        row = _audit_target(w)
        buckets[w["role"]] = row.pop("_findings")
        audits.append(row)

    from hexstrike.mcp.solidity_audit_runner import normalize_findings

    normalized = normalize_findings(buckets)

    print("[4/4] Write report...")
    bundle = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "profile": "web3-orchestrator",
        "targets_file": str(TARGETS_FILE),
        "pool_root": str(POOL_ROOT),
        "ingest": ingest,
        "audits": [{k: v for k, v in a.items() if k != "_findings"} for a in audits],
        "normalized": normalized,
    }
    json_path = OUT / "test-celi-full-run.json"
    json_path.write_text(json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8")

    sev: dict[str, int] = {}
    for f in normalized.get("deduped_findings") or []:
        s = f.get("severity", "info")
        sev[s] = sev.get(s, 0) + 1

    lines = [
        "# TEST ЦЕЛИ — full run report",
        "",
        f"**Started:** {started}",
        f"**Targets:** `field-targets-3.json` (3 BSC)",
        f"**Pool:** `{POOL_ROOT}`",
        "",
        "## Summary",
        "",
        "| role | address | type | findings | key |",
        "|------|---------|------|----------|-----|",
    ]
    for a in audits:
        rpc = a["tools"]["rpc_contract_audit"]
        wr = a["tools"]["rpc_wallet_risk"]
        typ = "contract" if rpc.get("is_contract") else "EOA"
        key = f"risk={wr.get('risk_score',0)}"
        if rpc.get("is_proxy"):
            key = f"proxy→{str(rpc.get('implementation_address',''))[:12]}…"
        if a["role"] == "hot_wallet":
            key = f"nonce={wr.get('nonce')} ~$2.1M recon"
        lines.append(f"| {a['role']} | `{a['address']}` | {typ} | {a['raw_finding_count']} | {key} |")

    lines += ["", f"**Deduped:** {normalized.get('finding_count')} | {sev}", "", "## Flow", "", "```", "hot_wallet → authority → sink_hub (Rhino.fi)", "```", "", "## Findings", ""]
    lines.append("| id | sev | description |")
    lines.append("|----|-----|-------------|")
    for i, f in enumerate(normalized.get("deduped_findings") or [], 1):
        lines.append(f"| F-{i:03d} | {f.get('severity')} | {(f.get('description') or '')[:100]} |")

    lines += ["", "## Artifacts", "", f"- `{json_path}`", f"- `{OUT / 'ingested-lite.json'}`", ""]
    md_path = OUT / "test-celi-full-run.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nDone: {md_path}")
    print(f"Deduped findings: {normalized.get('finding_count')} {sev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
