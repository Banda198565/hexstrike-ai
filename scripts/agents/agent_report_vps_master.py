#!/usr/bin/env python3
"""Agent-Report-06: consolidate VPS/full-run artifacts into master report."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts"
OUT = ART / "vps-master-report.json"

ARTIFACTS = [
    "infra-targets.json",
    "multichain-cluster.json",
    "entity-id.json",
    "web-recon.json",
    "jenkins-cve-report.json",
    "defensive-audit-template.md",
    "recon-master-report.json",
]


def load(name: str) -> dict | str | None:
    path = ART / name
    if not path.exists():
        return None
    if name.endswith(".md"):
        return path.read_text()[:2000]
    with open(path) as f:
        return json.load(f)


def highlights(data: dict) -> list[str]:
    lines: list[str] = []
    mc = data.get("multichain-cluster.json") or {}
    if isinstance(mc, dict):
        nw = mc.get("net_worth_usd") or mc.get("summary", {}).get("net_worth_usd")
        if nw:
            lines.append(f"Net worth: ${nw:,.0f}" if isinstance(nw, (int, float)) else f"Net worth: {nw}")
    ent = data.get("entity-id.json") or {}
    if isinstance(ent, dict):
        e = ent.get("entity_resolution") or ent.get("entity") or ent.get("resolution", {})
        if isinstance(e, dict):
            name = e.get("status") or e.get("name", "UNIDENTIFIED")
            conf = e.get("confidence", "?")
            lines.append(f"Entity: {name} (confidence: {conf})")
    jenkins = data.get("jenkins-cve-report.json") or {}
    if isinstance(jenkins, dict):
        cves = jenkins.get("cves_march_2023_advisory") or []
        ver = jenkins.get("target") or jenkins.get("observed_instance", {}).get("fingerprint", {}).get("X-Jenkins")
        lines.append(f"Jenkins {ver}: {len(cves)} CVEs (passive)")
    web = data.get("web-recon.json") or {}
    if isinstance(web, dict):
        probes = web.get("probes") or web.get("results") or []
        ok = sum(1 for p in probes if isinstance(p, dict) and p.get("ok"))
        lines.append(f"Web probes: {ok}/{len(probes)} responded" if probes else "Web probes: see web-recon.json")
    return lines


def main() -> int:
    out_path = Path(os.environ.get("OUTPUT", OUT))
    bundled: dict = {}
    for name in ARTIFACTS:
        bundled[name] = load(name)

    latest = None
    latest_path = ART / "orchestrator" / "latest.json"
    if latest_path.exists():
        with open(latest_path) as f:
            latest = json.load(f)

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": "Agent-Report-06",
        "task": "generate-vps-master-report",
        "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "mode": "read-only_passive",
        "orchestrator_latest": latest,
        "highlights": highlights(bundled),
        "artifacts_present": [k for k, v in bundled.items() if v is not None],
        "artifacts_missing": [k for k, v in bundled.items() if v is None],
        "artifacts": {k: v for k, v in bundled.items() if v is not None and not k.endswith(".md")},
        "disclosure_pack": "artifacts/disclosure-pack/",
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Wrote {out_path}")
    print("Highlights:")
    for h in report["highlights"]:
        print(f"  • {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
