#!/usr/bin/env python3
"""Agent-Contract-04 — CREATE2 / EIP-1167 factory pipeline static analysis (read-only)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from forensics_common import ROOT, emit, output_path, utc_now, write_json

SCHEMA = "hexstrike.create2-drainer.v1"
CREATE2_MARKERS = ("create2", "CREATE2", "0xf5", "EIP-1167", "clone", "minimal proxy")


def main() -> int:
    scan_roots = os.environ.get(
        "CREATE2_SCAN_ROOTS",
        f"{ROOT / 'artifacts' / 'intel' / 'apeterminal-main'}:{ROOT / 'artifacts' / 'intel' / 'evm-drainer'}:{ROOT / 'artifacts'}",
    ).split(":")
    flagged: list[str] = []
    claim_contracts: set[str] = set()

    for root_s in scan_roots:
        root = Path(root_s.strip())
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".js", ".ts", ".tsx", ".jsx", ".sol", ".json"}:
                continue
            if any(p in path.parts for p in {".git", "node_modules", "dist", ".next"}):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(m in text for m in CREATE2_MARKERS):
                flagged.append(str(path))
            if "claim" in text.lower() and "contract" in text.lower():
                for token in text.split():
                    if token.startswith("0x") and len(token) == 42:
                        claim_contracts.add(token.lower())

    out = output_path("create2-drainer-iocs.json")
    report = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "sample": {
            "name": "CREATE2 Drainer Evasion",
            "classification": "deterministic_contract_deployment_abuse",
            "standards": ["EIP-1014", "EIP-1167"],
        },
        "eip1014_reference": {
            "opcode": "0xf5",
            "drainer_ttp": [
                "Deploy fresh claim/drain contract per phishing domain",
                "Evade static blocklists that target fixed addresses",
                "Salt grinding for vanity or cross-chain address reuse",
                "Minimal proxy (EIP-1167) + CREATE2 factory pipelines",
            ],
        },
        "files_flagged": flagged,
        "claim_contracts_correlated": sorted(claim_contracts),
    }
    write_json(out, report)
    return emit({
        "success": True,
        "agent": "Agent-Contract-04",
        "task": "create2-analyze",
        "output": str(out),
        "classification": "deterministic_contract_deployment_abuse",
        "files_flagged": len(flagged),
        "claim_contracts_correlated": len(claim_contracts),
    })


if __name__ == "__main__":
    sys.exit(main())
