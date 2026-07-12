#!/usr/bin/env python3
"""Agent-Contract-03 — EIP-2612 permit farming static analysis (read-only)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from forensics_common import ROOT, emit, output_path, scan_tree, utc_now, write_json

SCHEMA = "hexstrike.permit-farming.v1"
PERMIT_SELECTOR = "0xd505accf"
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"


def main() -> int:
    roots = [
        Path(os.environ.get("APETERMINAL_REPO", str(ROOT / "artifacts" / "intel" / "apeterminal-main"))),
        Path(os.environ.get("EVM_DRAINER_REPO", str(ROOT / "artifacts" / "intel" / "evm-drainer"))),
    ]
    flagged: list[str] = []
    spenders: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".js", ".ts", ".tsx", ".jsx", ".sol"}:
                continue
            if any(p in path.parts for p in {".git", "node_modules", "dist", ".next"}):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "permit" in text.lower() or PERMIT_SELECTOR in text or "signTypedData" in text:
                flagged.append(str(path.relative_to(root)))
            for token in text.split():
                if token.startswith("0x") and len(token) == 42:
                    spenders.add(token.lower())

    out = output_path("permit-farming-eip2612-iocs.json")
    report = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "sample": {
            "name": "EIP-2612 Permit Farming",
            "classification": "offchain_signature_allowance_abuse",
            "standards": ["EIP-2612", "EIP-712", "Permit2"],
        },
        "eip2612_reference": {
            "permit_selector": PERMIT_SELECTOR,
            "permit2_contract": PERMIT2,
        },
        "files_flagged": flagged,
        "spenders_correlated": sorted(spenders),
    }
    write_json(out, report)
    return emit({
        "success": True,
        "agent": "Agent-Contract-03",
        "task": "permit-farming-analyze",
        "output": str(out),
        "classification": "offchain_signature_allowance_abuse",
        "files_flagged": len(flagged),
        "spenders_correlated": len(spenders),
    })


if __name__ == "__main__":
    sys.exit(main())
