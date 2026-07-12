#!/usr/bin/env python3
"""Forensics analyzers — enrich IOC artifacts via HexStrike orchestrator (read-only)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_instruction_file(name: str) -> str:
    path = ROOT / "src" / "hexstrike" / "instructions" / name
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return f"# {name}\nRead-only defensive forensics protocol.\n"


def load_ioc(name: str) -> dict:
    path = ROOT / "artifacts" / name
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(kind: str) -> dict:
    instruction_map = {
        "trx": "trx_drainer_forensics.md",
        "evm": "evm_drainer_forensics.md",
        "apeterminal": "apeterminal_forensics.md",
        "solana": "solana_drainer_forensics.md",
        "vanilla": "vanilla_drainer_forensics.md",
        "permit": "permit_farming_forensics.md",
        "create2": "create2_drainer_forensics.md",
    }
    ioc_map = {
        "trx": "trx-drainer-tool-iocs.json",
        "evm": "evm-drainer-iocs.json",
        "apeterminal": "apeterminal-main-iocs.json",
        "solana": "solana-drainer-tool-iocs.json",
        "vanilla": "vanilla-drainer-iocs.json",
        "permit": "permit-farming-eip2612-iocs.json",
        "create2": "create2-drainer-iocs.json",
    }
    instruction_file = instruction_map[kind]
    prompt = load_instruction_file(instruction_file)

    ioc = load_ioc(ioc_map[kind])
    report = {
        "instruction_loaded": instruction_file,
        "instruction_bytes": len(prompt),
        "report": ioc,
        "generated_at": utc_now(),
    }

    if kind == "vanilla":
        fee = ioc.get("onchain_iocs", {}).get("fee_wallet")
        if fee:
            try:
                from hexstrike_orchestrator import HexStrikeOrchestrator  # type: ignore

                orch = HexStrikeOrchestrator()
                report["onchain"] = orch.run_analyze(fee)
            except Exception as exc:  # noqa: BLE001
                report["onchain_error"] = str(exc)

    if kind == "create2":
        try:
            from hexstrike.core.forensics.engine import ForensicsEngine  # noqa: E402
            from hexstrike.bus.context_bus import ContextBus  # noqa: E402

            engine = ForensicsEngine(bus=ContextBus())
            addrs = ioc.get("claim_contracts_correlated") or []
            report["bytecode"] = [engine.analyze_contract(a) for a in addrs[:2]]
        except Exception as exc:  # noqa: BLE001
            report["bytecode_error"] = str(exc)

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["trx", "evm", "apeterminal", "solana", "vanilla", "permit", "create2"])
    args = parser.parse_args()
    result = analyze(args.kind)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
