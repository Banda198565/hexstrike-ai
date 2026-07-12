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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mcp"))

from lib.evm_client import EvmClient, OFFICIAL_USDT_BSC, WBNB_BSC  # noqa: E402

OUT = ROOT / "artifacts" / "sandbox" / "field-recon-bundle.json"
USDT = OFFICIAL_USDT_BSC

DEFAULT_RPCS = [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.ninicoin.io",
    "https://bsc.publicnode.com",
]


def rpc_pool() -> list[str]:
    raw = os.environ.get("BSC_HTTP_URLS", os.environ.get("BSC_HTTP_URL", ""))
    urls = [u.strip() for u in raw.split(",") if u.strip()] if raw else []
    if not urls:
        urls = list(DEFAULT_RPCS)
    fb = os.environ.get("BSC_HTTP_FALLBACK", "").strip()
    if fb and fb not in urls:
        urls.append(fb)
    return urls


def load_previous() -> dict | None:
    if os.environ.get("FIELD_RECON_INCREMENTAL", "0") != "1" or not OUT.is_file():
        return None
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return None


def wallet_unchanged(prev: dict | None, w: dict) -> bool:
    if not prev:
        return False
    addr = w["address"].lower()
    for row in prev.get("wallets", []):
        if row.get("address", "").lower() == addr:
            return True
    return False


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
    pool = rpc_pool()
    rpc = pool[0]
    c = EvmClient(rpc)
    chain_id = int(c.rpc("eth_chainId", []), 16)
    prev = load_previous()
    parallel = int(os.environ.get("FIELD_RECON_PARALLEL", "1"))

    wallet_jobs: list[tuple] = []
    for w in catalog.get("wallets", []):
        cached = None
        if prev:
            for row in prev.get("wallets", []):
                if row.get("address", "").lower() == w["address"].lower():
                    cached = row
                    break
        if cached and os.environ.get("FIELD_RECON_INCREMENTAL", "0") == "1":
            wallet_jobs.append((w, cached, True))
        else:
            wallet_jobs.append((w, None, False))

    wallets: list[dict] = []

    def _recon_one(item: tuple) -> dict:
        w, cached, is_cached = item
        if is_cached and cached:
            out = dict(cached)
            out["incremental"] = "cached"
            return out
        idx = abs(hash(w["address"])) % len(pool)
        client = EvmClient(pool[idx])
        print(f"[recon] {w.get('role')} {w['address']} rpc={pool[idx][:40]}")
        row = recon_wallet(client, w)
        row["incremental"] = "fresh"
        return row

    if parallel > 1 and len(wallet_jobs) > 1:
        with ThreadPoolExecutor(max_workers=min(parallel, len(wallet_jobs))) as ex:
            futs = [ex.submit(_recon_one, j) for j in wallet_jobs]
            for fut in as_completed(futs):
                wallets.append(fut.result())
        wallets.sort(key=lambda x: x.get("priority") or 99)
    else:
        for item in wallet_jobs:
            wallets.append(_recon_one(item))

    deltas: list[dict] = []
    if prev:
        prev_by_addr = {r["address"].lower(): r for r in prev.get("wallets", [])}
        for w in wallets:
            old = prev_by_addr.get(w["address"].lower())
            if not old:
                continue
            if "usdt" in w and "usdt" in old and w["usdt"] != old["usdt"]:
                deltas.append({
                    "address": w["address"],
                    "role": w.get("role"),
                    "usdt_delta": round(w["usdt"] - old["usdt"], 2),
                    "bnb_delta": round(w.get("bnb", 0) - old.get("bnb", 0), 6),
                })

    infra = recon_infra(catalog.get("infra_targets", []))
    pair = c.pancake_pair(USDT, WBNB_BSC)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "field_recon_read_only",
        "incremental": os.environ.get("FIELD_RECON_INCREMENTAL", "0") == "1",
        "parallel_workers": parallel,
        "rpc_pool": pool,
        "chain_id": chain_id,
        "rpc": rpc,
        "wallet_count": len(wallets),
        "wallets": wallets,
        "infra": infra,
        "hot_wallet_deltas": deltas,
        "pancake_usdt_wbnb_pair": pair,
        "summary": {
            "total_bnb": round(sum(w.get("bnb", 0) for w in wallets), 4),
            "hot_usdt": sum(w.get("usdt", 0) for w in wallets if "usdt" in w),
            "high_nonce": [w["role"] for w in wallets if w.get("nonce", 0) > 1000],
            "infra_reachable": [i["role"] for i in infra if i.get("reachable")],
            "cached_wallets": sum(1 for w in wallets if w.get("incremental") == "cached"),
            "fresh_wallets": sum(1 for w in wallets if w.get("incremental") == "fresh"),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] → {OUT}")
    print(f"[OK] summary: {payload['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
