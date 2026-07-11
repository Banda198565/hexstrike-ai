#!/usr/bin/env python3
"""Build sandbox target-profile.json from HexStrike recon artifacts (read-only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts"
OUT = ROOT / "artifacts" / "sandbox" / "target-profile.json"


def load_json(name: str) -> dict:
    p = ART / name
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    infra = load_json("infra-targets.json")
    entity = load_json("entity-id.json")
    graph = load_json("hot-wallet-onchain-graph.json")
    authority = load_json("authority-contract-analysis.json")

    seeds = infra.get("seed_addresses", {})
    hot = (
        seeds.get("hot_wallet")
        or entity.get("target")
        or graph.get("hot_wallet")
        or "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA"
    )

    profile = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only_recon",
        "scope": "authorized_defensive_research",
        "primary_target": {
            "role": "hot_wallet",
            "address": hot,
            "chain": "BSC",
            "chain_id": 56,
            "labels": entity.get("methods", {}).get("bscan_labels", {}),
            "graph_summary": {
                "usdt_out_txs": graph.get("usdt_out_txs"),
                "net_usdt_period": graph.get("net_usdt_period"),
                "top_destinations": (graph.get("top_destinations") or [])[:5],
            },
        },
        "related_targets": {
            "authority": seeds.get("authority") or authority.get("address"),
            "primary_sink_hub": seeds.get("primary_sink_hub"),
            "operator_local": seeds.get("operator_local"),
        },
        "rpc_endpoints": {
            "bsc_public": "https://bsc-dataseed.binance.org",
            "bsc_fallback": "https://bsc-dataseed1.binance.org",
            "local_fork": "http://127.0.0.1:8545",
        },
        "battle_modes": {
            "local_dummy": {
                "description": "Anvil mnemonic bot — 7 offensive sandbox attacks",
                "command": "./bin/hexstrike-agent battle",
                "requires": ["foundry", "anvil.env with test keys"],
            },
            "fork_watch": {
                "description": "Anvil fork of BSC at hot wallet — read-only + balance simulation",
                "command": "./scripts/sandbox/setup-real-target-fork.sh && ./scripts/sandbox/run-target-recon.sh",
                "requires": ["foundry", "network"],
                "note": "No private key for third-party address — signing tests use DRY_RUN",
            },
            "authorized_testnet": {
                "description": "Your own bot on Sepolia/BSC testnet with your keys",
                "command": "Set BOT_ADDRESS + BOT_PRIVATE_KEY in anvil.env, HARDENING_ENABLED=true",
                "requires": ["operator-owned wallet", "explicit authorization"],
            },
        },
        "constraints": [
            "no_remote_exploit",
            "no_balance_drain",
            "no_unsigned_mainnet_tx",
            "read-only unless operator owns keys",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote {OUT}")
    print(f"     primary_target: {hot} (BSC hot wallet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
