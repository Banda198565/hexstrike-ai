#!/usr/bin/env python3
"""Read-only multichain outflow analyzer (Blockscout + optional RPC)."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOT_DEFAULT = "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA"
AUTHORITY = "0x730ea0231808f42a20f8921ba7fbc788226768f5"

CHAIN_CONFIG = {
    "base": {
        "explorer_api": "https://base.blockscout.com/api",
        "stable": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "stable_symbol": "USDC",
        "decimals": 6,
        "rpc": "https://base-rpc.publicnode.com",
    },
    "bsc": {
        "explorer_api": "https://api.bscscan.com/api",
        "stable": "0x55d398326f99059fF775485246999027B3197955",
        "stable_symbol": "USDT",
        "decimals": 18,
        "rpc": "https://bsc-dataseed.binance.org/",
    },
}

# Known labels for Base (read-only reference set)
TAGS_BASE = {
    "0x3304e22d7222793999f1c52ea872670d4c376105": "OKX Deposit (Base)",
    "0xa238dd80c259a72e81d7e4664a98015996309a1": "Aave V3 Pool (Base)",
    "0xb125e6687d4313864e53df431d0a6fad266a845": "Compound Comet USDC (Base)",
    "0x49048044d58183ce9aac715e93e415ef3550a5": "L2 Standard Bridge (Base)",
    "0xc1cb737585dba865437c6fa9475c8e7a94e04b5": "Moonwell USDC Market (Base)",
    "0x2ae3f1ec2565d3e5923308eaaad9bc4e1b862fe5": "Across Base Spoke Pool",
    "0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae": "LiFi Diamond",
    "0xf89d7b9c864fbb9a8758c8c1748e7e08d8c088a": "Bybit Hot Wallet",
    "0x28c6c06298d410dbbae40afa1521352b78362942": "Binance Hot Wallet 14 (ETH/Base ref)",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance Hot Wallet 8",
    "0x730ea0231808f42a20f8921ba7fbc788226768f5": "Authority EIP-7702 (BSC cluster)",
    "0xb80a582fa430645a043bb4f6135321ee01005fef": "Rhino.fi Bridge (BSC)",
}

BSC_HOPS = {
    "0x730ea0231808f42a20f8921ba7fbc788226768f5",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a",
    "0x3e0b65c9c31e9593e2b357be6eecd28bef6da03e",
    "0xd0b5b1fa9122696bcab0cc5d5f4421e6d94a9e52",
    "0x2a3cba35c2b427850c2047b2d79164a6227ebe7b",
    "0x831c7f9ea511a161c037b6b682ade7d46695a08f",
    "0x6977262a9a9b2eaaf7c20903b45798b1676ea7fd",
}


def tag(addr: str, chain: str) -> str | None:
    return TAGS_BASE.get(addr.lower())


def explorer_tokentx(chain: str, address: str, page: int, offset: int, retries: int = 5) -> list[dict]:
    cfg = CHAIN_CONFIG[chain]
    params = urllib.parse.urlencode({
        "module": "account",
        "action": "tokentx",
        "address": address,
        "contractaddress": cfg["stable"],
        "page": page,
        "offset": offset,
        "sort": "desc",
    })
    url = f"{cfg['explorer_api']}?{params}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hexstrike-forensics/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            if data.get("status") == "0" and data.get("message") not in ("No transactions found", "OK"):
                raise RuntimeError(data.get("result") or data.get("message"))
            result = data.get("result", [])
            return result if isinstance(result, list) else []
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(last_err)


def rpc_call(chain: str, method: str, params: list) -> object:
    cfg = CHAIN_CONFIG[chain]
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(cfg["rpc"], data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def stable_balance(chain: str, address: str) -> float | None:
    try:
        cfg = CHAIN_CONFIG[chain]
        data = "0x70a08231" + address.lower().replace("0x", "").zfill(64)
        raw = rpc_call(chain, "eth_call", [{"to": cfg["stable"], "data": data}, "latest"])
        return round(int(raw, 16) / (10 ** cfg["decimals"]), 2)
    except Exception:
        return None


def analyze_base_outflows(target: str, depth: int, max_pages: int = 10, page_size: int = 100) -> dict:
    target_l = target.lower()
    cfg = CHAIN_CONFIG["base"]
    all_txs: list[dict] = []

    for page in range(1, max_pages + 1):
        batch = explorer_tokentx("base", target, page, page_size)
        if not batch:
            break
        all_txs.extend(batch)
        if len(batch) < page_size:
            break
        time.sleep(0.6)

    outflows: list[dict] = []
    inflows: list[dict] = []
    recipients: dict[str, float] = defaultdict(float)
    senders: dict[str, float] = defaultdict(float)
    protocol_hits: dict[str, list] = defaultdict(list)
    cex_hits: dict[str, list] = defaultdict(list)
    bsc_correlation: dict[str, list] = defaultdict(list)

    for tx in all_txs:
        frm = tx.get("from", "").lower()
        to = tx.get("to", "").lower()
        val = int(tx.get("value", 0)) / (10 ** cfg["decimals"])
        row = {
            "tx": tx.get("hash"),
            "from": frm,
            "to": to,
            "amount_usdc": round(val, 2),
            "block": int(tx.get("blockNumber", 0)),
            "timestamp": int(tx.get("timeStamp", 0)),
            "tag_to": tag(to, "base"),
            "tag_from": tag(frm, "base"),
            "basescan": f"https://basescan.org/tx/{tx.get('hash')}",
        }

        if frm == target_l:
            outflows.append(row)
            recipients[to] += val
            lbl = tag(to, "base")
            if lbl:
                if any(x in lbl.lower() for x in ("okx", "bybit", "binance", "coinbase")):
                    cex_hits[lbl].append(row)
                elif any(x in lbl.lower() for x in ("aave", "compound", "moonwell", "bridge", "lifi")):
                    protocol_hits[lbl].append(row)
            if to in BSC_HOPS or to == AUTHORITY.lower():
                bsc_correlation["recipient_is_bsc_hop"].append(row)
        elif to == target_l:
            inflows.append(row)
            senders[frm] += val
            if frm in BSC_HOPS or frm == AUTHORITY.lower():
                bsc_correlation["sender_is_bsc_hop"].append(row)

    top_out = sorted(recipients.items(), key=lambda x: -x[1])[:25]
    top_in = sorted(senders.items(), key=lambda x: -x[1])[:15]

    # depth-2: scan top 8 recipients' outbound USDC (1 page each)
    depth2 = {}
    for addr, total_in in top_out[:8]:
        addr_l = addr.lower()
        if tag(addr_l, "base"):
            depth2[addr_l] = {"skipped": "tagged protocol/cex", "received_usdc": round(total_in, 2)}
            continue
        try:
            sub = explorer_tokentx("base", addr, 1, 50)
            sub_out = []
            for t in sub:
                if t.get("from", "").lower() != addr_l:
                    continue
                tto = t.get("to", "").lower()
                v = int(t.get("value", 0)) / 1e6
                tl = tag(tto, "base")
                entry = {"to": tto, "amount_usdc": round(v, 2), "tag": tl, "tx": t.get("hash")}
                sub_out.append(entry)
                if tl and any(x in tl.lower() for x in ("okx", "bybit", "binance", "coinbase")):
                    cex_hits[f"depth2::{tl}"].append({**entry, "hop": addr_l})
            depth2[addr_l] = {
                "received_from_hot_usdc": round(total_in, 2),
                "out_sample": sub_out[:10],
                "cex_in_sample": [x for x in sub_out if x.get("tag")],
            }
            time.sleep(0.2)
        except Exception as exc:
            depth2[addr_l] = {"error": str(exc)}

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_at": now,
        "task": "base-usdc-outflow-trace",
        "mode": "read-only",
        "chain": "base",
        "target": target,
        "depth": depth,
        "stable": cfg["stable"],
        "scan_params": {"pages": max_pages, "page_size": page_size, "tx_rows_fetched": len(all_txs)},
        "live_balance_usdc": stable_balance("base", target),
        "summary": {
            "outflow_tx_count": len(outflows),
            "inflow_tx_count": len(inflows),
            "unique_outflow_recipients": len(recipients),
            "total_outflow_usdc_sampled": round(sum(recipients.values()), 2),
            "total_inflow_usdc_sampled": round(sum(senders.values()), 2),
            "cex_hits_count": sum(len(v) for v in cex_hits.values()),
            "protocol_hits_count": sum(len(v) for v in protocol_hits.values()),
            "bsc_hop_correlation_rows": sum(len(v) for v in bsc_correlation.values()),
        },
        "top_outflow_recipients": [
            {"address": a, "total_usdc": round(v, 2), "tag": tag(a, "base"), "basescan": f"https://basescan.org/address/{a}"}
            for a, v in top_out
        ],
        "top_inflow_senders": [
            {"address": a, "total_usdc": round(v, 2), "tag": tag(a, "base"), "is_bsc_hop": a in BSC_HOPS}
            for a, v in top_in
        ],
        "cex_hits": dict(cex_hits),
        "protocol_hits": dict(protocol_hits),
        "cross_chain_correlation": dict(bsc_correlation),
        "depth2_recipient_scans": depth2,
        "sample_recent_outflows": outflows[:30],
        "verdict": {
            "cex_deposits_found": bool(cex_hits),
            "defi_protocol_usage": bool(protocol_hits),
            "authority_on_base": any(
                AUTHORITY.lower() in (r.get("from", ""), r.get("to", ""))
                for r in outflows + inflows
            ),
            "pattern": "payroll/disbursement" if len(recipients) > 20 else "concentrated",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze stablecoin outflows on Base/BSC")
    parser.add_argument("--target", default=HOT_DEFAULT)
    parser.add_argument("--chain", default="base", choices=["base"])
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--output", default="artifacts/exchange-forensics/base-outflow-trace.json")
    args = parser.parse_args()

    if args.chain != "base":
        raise SystemExit("Only base chain implemented in this pass")

    result = analyze_base_outflows(args.target, args.depth, max_pages=args.pages)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    out_path.write_text(text, encoding="utf-8")

    desktop = Path.home() / "Desktop/on-chain-forensics/artifacts" / out_path.name
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(text, encoding="utf-8")

    print(f"[+] Wrote {out_path}")
    print(json.dumps(result["summary"], indent=2))
    print(json.dumps(result["verdict"], indent=2))


if __name__ == "__main__":
    main()
