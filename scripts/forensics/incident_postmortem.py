#!/usr/bin/env python3
"""Generate incident post-mortem JSON bundle (worst-case IR plan)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "forensics" / "incident-total-compromise.json"
MD = ROOT / "docs" / "forensics" / "INCIDENT-TOTAL-COMPROMISE-POSTMORTEM.md"

HOT = "0x4943f5e7f4e450d48ae82026163ecde8a52c53da"

payload = {
    "case_id": "HEX-2026-07-12-TOTAL-COMPROMISE",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "document_type": "incident_post_mortem_worst_case",
    "mode": "defensive_ir",
    "actual_state": {
        "jenkins_rce_proven": True,
        "open_bsc_rpc_proven": True,
        "private_key_obtained": False,
        "drain_executed": False,
        "payroll_otc_verdict": "CLOSED_MEDIUM_HIGH",
    },
    "worst_case_assumption": {
        "private_key_compromised": True,
        "jenkins_credentials_compromised": True,
        "geth_node_control": True,
        "signing_service_compromised": True,
    },
    "target": HOT,
    "infra": {
        "jenkins": "51.250.97.223:8080",
        "geth_rpc": "51.222.42.220:8545",
    },
    "ir_phases": ["containment", "asset_rescue", "eradication", "recovery"],
    "verdict_actual": "Perimeter exposed; key not confirmed leaked; drain blocked",
    "verdict_worst_case": "Infrastructure unfit; keys burned; greenfield + new payout rail required",
    "markdown_source": str(MD.relative_to(ROOT)),
    "related_artifacts": [
        "artifacts/forensics/hot-wallet-dossier.json",
        "artifacts/forensics/payroll-otc-verdict.json",
        "artifacts/entity-id.json",
        "artifacts/jenkins-cve-report.json",
    ],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"success": True, "output": str(OUT)}, indent=2))
