#!/usr/bin/env python3
"""Operator mainnet rescue dry-run — BOT 0x85dB… + Puissant sim (no submit)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
ART = ROOT / "artifacts" / "sandbox"
OUT = ART / "operator-rescue-puissant.json"

sys.path.insert(0, str(SANDBOX / "mev"))
from builder_sim import simulate_bundle  # noqa: E402

OPERATOR_BOT = "0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846"
TARGET_WATCH = "0x96B23C4680E1a37cE17730e6118D0C9223e72A66"
SAFE_FUNDER = "0x060447dC91dfb22A5233731aF67E9E8dafdF24d1"


def rpc_balance(url: str, addr: str) -> int:
    import urllib.request

    body = json.dumps({
        "jsonrpc": "2.0", "method": "eth_getBalance", "params": [addr, "latest"], "id": 1,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        out = json.loads(r.read())
    return int(out["result"], 16)


def local_gas_oracle(rpc: str) -> dict:
    """Local gas oracle — single eth_gasPrice, no external API."""
    body = json.dumps({"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1}).encode()
    req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        out = json.loads(r.read())
    gas = int(out["result"], 16)
    return {"gas_price_wei": gas, "max_fee_wei": gas * 2, "priority_wei": gas, "source": "local_oracle"}


def prefetch_operator_state(rpc: str, bot: str) -> dict:
    body_nonce = json.dumps({
        "jsonrpc": "2.0", "method": "eth_getTransactionCount",
        "params": [bot, "pending"], "id": 1,
    }).encode()
    req = urllib.request.Request(rpc, data=body_nonce, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        nonce = int(json.loads(r.read())["result"], 16)
    return {"bot_nonce_pending": nonce, "prefetch": True}


def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"
    rpc = os.environ.get("RPC_URL", os.environ.get("BSC_HTTP_URL", "https://bsc-dataseed.binance.org"))
    threshold = int(os.environ.get("THRESHOLD_WEI", "500000000000000000"))
    rescue_value = int(os.environ.get("RESCUE_VALUE_WEI", "1000000000000000"))
    endpoint = os.environ.get("PUISSANT_BUILDER_URL", "https://puissant-builder.48.club/")
    prefetch = os.environ.get("RESCUE_PREFETCH", "0") == "1"

    gas_oracle = local_gas_oracle(rpc) if prefetch else {}
    bot_prefetch = prefetch_operator_state(rpc, OPERATOR_BOT) if prefetch else {}

    try:
        target_bal = rpc_balance(rpc, TARGET_WATCH)
        bot_bal = rpc_balance(rpc, OPERATOR_BOT)
    except Exception as exc:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "operator_rescue_dry_run",
            "dry_run": True,
            "error": str(exc),
            "operator_bot": OPERATOR_BOT,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"[FAIL] balance probe: {exc}", file=sys.stderr)
        return 1

    would_trigger = target_bal < threshold
    network_fee = gas_oracle.get("max_fee_wei") or int(os.environ.get("NETWORK_FEE_WEI", "630000000000000000"))
    sim = simulate_bundle(
        gross_profit_wei=0,
        network_fee_wei=network_fee,
        attack_type="rescue_evacuation",
    )
    sim["endpoint"] = endpoint
    sim["would_submit"] = False
    sim["dry_run"] = dry_run

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "operator_rescue_puissant_dry_run",
        "dry_run": dry_run,
        "operator_bot": OPERATOR_BOT,
        "target_watch": TARGET_WATCH,
        "safe_funder": SAFE_FUNDER,
        "rpc": rpc,
        "balances_wei": {"target": target_bal, "bot": bot_bal},
        "threshold_wei": threshold,
        "rescue_value_wei": rescue_value,
        "would_trigger_rescue": would_trigger,
        "puissant_sim": sim,
        "gas_oracle": gas_oracle,
        "bot_prefetch": bot_prefetch,
        "flow": "poll TARGET → BOT signs rescue → Puissant bundle → SAFE",
        "constraints": ["operator-owned-wallets-only", "DRY_RUN default", "no-third-party-drain"],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"[OK] operator rescue dry-run trigger={would_trigger} "
        f"target={target_bal} bot={bot_bal} → {OUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
