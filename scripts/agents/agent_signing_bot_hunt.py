#!/usr/bin/env python3
"""Agent: locate signing-bot custody hypotheses from local artifacts (read-only)."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "sandbox" / "signing-bot-hunt.json"

ARTIFACTS = [
    ROOT / "artifacts" / "infra-targets.json",
    ROOT / "artifacts" / "entity-id.json",
    ROOT / "artifacts" / "web-recon.json",
    ROOT / "artifacts" / "sandbox" / "field-recon-bundle.json",
    ROOT / "artifacts" / "sandbox" / "target-profiles.json",
]

REPORT_GLOBS = [
    ROOT / "docs",
    ROOT / "artifacts",
]

PATTERNS = [
    (re.compile(r"eth_accounts\s*=\s*\[\]", re.I), "rpc_no_unlocked_accounts"),
    (re.compile(r"personal_\w+", re.I), "personal_module_reference"),
    (re.compile(r"signing\s+bot", re.I), "signing_bot_mention"),
    (re.compile(r"jenkins", re.I), "jenkins_surface"),
    (re.compile(r"51\.250\.97\.223", re.I), "yandex_jenkins_host"),
    (re.compile(r"51\.222\.42\.220", re.I), "ovh_geth_rpc_host"),
    (re.compile(r"key_extraction", re.I), "key_extraction_note"),
    (re.compile(r"external\s+sign", re.I), "external_signing"),
    (re.compile(r"BOT_PRIVATE_KEY", re.I), "operator_key_env"),
]


def load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_text(path: Path, text: str) -> list[dict]:
    hits = []
    for rx, tag in PATTERNS:
        if rx.search(text):
            hits.append({"tag": tag, "source": str(path.relative_to(ROOT))})
    return hits


def scan_reports() -> list[dict]:
    hits: list[dict] = []
    for base in REPORT_GLOBS:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".md", ".json", ".txt"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits.extend(scan_text(path, text))
    return hits


def infra_hypotheses(infra: dict | None) -> list[dict]:
    rows = []
    if not isinstance(infra, dict):
        return rows
    for item in infra.get("infra_targets", []):
        ip = item.get("ip") or item.get("host")
        vec = item.get("key_extraction_vector") or item.get("services", {}).get("json_rpc_8545", {})
        if isinstance(vec, dict):
            vec = vec.get("note", "json_rpc_surface")
        rows.append({
            "host": ip,
            "service": item.get("service") or item.get("services"),
            "key_vector": vec,
            "link": item.get("link_to_hot_wallet"),
            "priority": item.get("priority"),
            "hypothesis": "keys_not_on_open_rpc" if "CLOSED" in str(vec) else "investigate_authorized_scope",
        })
    return rows


def build_hypotheses() -> list[dict]:
    return [
        {
            "id": "H1-external-signing-bot",
            "confidence": "high",
            "summary": "Hot wallet keys live on external signing service, not on 51.222.42.220 RPC",
            "evidence": ["eth_accounts=[]", "no personal_* on public RPC", "high nonce EOA with no local key"],
            "remediation": "Map Jenkins credential store / CI deploy keys under authorized scope",
        },
        {
            "id": "H2-jenkins-custody",
            "confidence": "medium",
            "summary": "Yandex Jenkins 51.250.97.223 may host deploy pipeline with signing bot",
            "evidence": ["Jenkins 2.375.3 fingerprint", "co-located RPC port 8545", "crypto ops stack pattern"],
            "remediation": "Passive CVE review + authorized credential audit only",
        },
        {
            "id": "H3-operator-local-key",
            "confidence": "high",
            "summary": "Operator BOT 0x85dB… key is local (.env) — separate from hot wallet custody",
            "evidence": ["mainnet.env.example BOT_PRIVATE_KEY", "deploy-mainnet.sh rescue loop"],
            "remediation": "Keep operator key in HSM / hardware wallet; never attach to MCP",
        },
        {
            "id": "H4-eip7702-delegate",
            "confidence": "medium",
            "summary": "Authority 0x730ea… uses EIP-7702 delegate — signing may be contract-gated",
            "evidence": ["authority_eip7702 in field-targets", "implementation 0x314C01e7…"],
            "remediation": "Bytecode audit of delegate + RBAC signer list",
        },
    ]


def main() -> int:
    loaded = {str(p): load_json(p) for p in ARTIFACTS}
    pattern_hits = scan_reports()
    infra = loaded.get(str(ROOT / "artifacts" / "infra-targets.json"))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": "Agent-Signing-Bot-Hunt",
        "mode": "read_only_hypothesis",
        "artifacts_scanned": [k for k, v in loaded.items() if v is not None],
        "pattern_hits": pattern_hits[:50],
        "infra_hypotheses": infra_hypotheses(infra if isinstance(infra, dict) else None),
        "hypotheses": build_hypotheses(),
        "operator_wallets": {
            "bot": "0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846",
            "target_watch": "0x96B23C4680E1a37cE17730e6118D0C9223e72A66",
            "safe_funder": "0x060447dC91dfb22A5233731aF67E9E8dafdF24d1",
        },
        "next_steps": [
            "Authorized Jenkins credential enumeration (scripts/pentest/jenkins-rpc-enum.sh)",
            "Geth RPC module probe from allowlisted IP (geth-rpc-enum.sh)",
            "Correlate signing bot process with hot_wallet nonce spikes",
        ],
        "constraints": ["no-exploit", "no-key-exfil", "authorized-lab-only"],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "output": str(OUT), "hypotheses": len(payload["hypotheses"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
