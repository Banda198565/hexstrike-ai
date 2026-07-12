#!/usr/bin/env python3
"""Full field recon — all report wallets + USDT graph + infra ping (read-only)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mcp"))

from lib.evm_client import EvmClient, OFFICIAL_USDT_BSC, WBNB_BSC  # noqa: E402

OUT = ROOT / "artifacts" / "sandbox" / "field-recon-bundle.json"
USDT = OFFICIAL_USDT_BSC


def load_catalog() -> dict:
    path = os.environ.get("WALLETS_FILE", str(SANDBOX / "field-targets-full.json"))
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def recon_wallet(c: EvmClient, w: dict) -> dict:
    addr = w["address"]
    role = w.get("role", "unknown")
    row: dict = {"role": role, "address": addr, "priority": w.get("priority")}
    wei = int(c.rpc("eth_getBalance", [addr, "latest"]), 16)
    nonce = int(c.rpc("eth_getTransactionCount", [addr, "latest"]), 16)
    code = c.get_code(addr)
    row.update({
        "bnb": round(wei / 1e18, 6),
        "nonce": nonce,
        "is_contract": code not in ("0x", "0x0"),
        "code_bytes": max(0, len(code) - 2) // 2,
    })
    if role in ("hot_wallet", "hot_wallet_2", "infra_correlated", "treasury_bnb") or not row["is_contract"]:
        try:
            row["usdt"] = round(c.balance_of(USDT, addr, 18), 2)
        except Exception as exc:
            row["usdt_error"] = str(exc)
    if role in ("hot_wallet", "hot_wallet_2"):
        try:
            tx = c.get_token_transfers(USDT, addr, "both", 15000, 50)
            row["usdt_transfer_count"] = tx.get("count", 0)
            dests: dict[str, float] = {}
            for t in tx.get("transfers", []):
                other = t["to"] if t.get("direction") == "out" else t["from"]
                if other.lower() == addr.lower():
                    continue
                dests[other] = dests.get(other, 0) + float(t.get("amount", 0))
            row["top_counterparties"] = [
                {"address": a, "usdt_volume": round(v, 2), "label": c.label(a)}
                for a, v in sorted(dests.items(), key=lambda x: -x[1])[:8]
            ]
        except Exception as exc:
            row["transfers_error"] = str(exc)
    if role == "authority_eip7702":
        stub = {"bytecode_bytes": row["code_bytes"]}
        if code.startswith("0xef0100") and len(code) >= 48:
            stub["eip7702_impl"] = "0x" + code[8:48]
        row["authority"] = stub
    if role == "puissant_validator":
        row["bscscan"] = f"https://bscscan.com/address/{addr}"
        row["note"] = "48Club Puissant validator — keys off-host"
    row["bscscan"] = f"https://bscscan.com/address/{addr}"
    return row


def recon_infra(targets: list[dict]) -> list[dict]:
    rows = []
    for t in targets:
        host = t["host"]
        open_ports = [p for p in t.get("ports", []) if port_open(host, p)]
        rows.append({
            "role": t.get("role"),
            "host": host,
            "ports_configured": t.get("ports", []),
            "ports_open": open_ports,
            "reachable": bool(open_ports),
        })
    return rows


def main() -> int:
    catalog = load_catalog()
    rpc = os.environ.get("BSC_HTTP_URL", "https://bsc-dataseed.binance.org")
    c = EvmClient(rpc)
    chain_id = int(c.rpc("eth_chainId", []), 16)

    wallets = []
    for w in catalog.get("wallets", []):
        print(f"[recon] {w.get('role')} {w['address']}")
        wallets.append(recon_wallet(c, w))

    infra = recon_infra(catalog.get("infra_targets", []))

    pair = c.pancake_pair(USDT, WBNB_BSC)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "field_recon_read_only",
        "chain_id": chain_id,
        "rpc": rpc,
        "wallet_count": len(wallets),
        "wallets": wallets,
        "infra": infra,
        "pancake_usdt_wbnb_pair": pair,
        "summary": {
            "total_bnb": round(sum(w.get("bnb", 0) for w in wallets), 4),
            "hot_usdt": sum(w.get("usdt", 0) for w in wallets if "usdt" in w),
            "high_nonce": [w["role"] for w in wallets if w.get("nonce", 0) > 1000],
            "infra_reachable": [i["role"] for i in infra if i.get("reachable")],
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] → {OUT}")
    print(f"[OK] summary: {payload['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
