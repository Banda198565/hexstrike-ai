#!/usr/bin/env python3
"""Mempool scanner — classifies pending swaps for offensive MEV pipeline (read-only RPC)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def rpc(url: str, method: str, params: list) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def scan_pending(url: str) -> list[dict]:
    """Return swap-like pending txs from txpool (Anvil) or empty on public RPC."""
    try:
        block = rpc(url, "eth_getBlockByNumber", ["pending", True])
    except Exception as exc:
        return [{"error": str(exc)}]

    txs = block.get("result", {}) or {}
    if isinstance(txs, dict):
        txs = txs.get("transactions") or []
    candidates = []
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        value = int(tx.get("value", "0x0"), 16)
        data = tx.get("input", "0x")
        if value <= 0 or len(data) < 10:
            continue
        sel = data[2:10].lower()
        if sel in ("7ff36ab5", "b6f9de95", "18cbafe5"):
            candidates.append(
                {
                    "hash": tx.get("hash"),
                    "from": tx.get("from"),
                    "to": tx.get("to"),
                    "value_wei": value,
                    "selector": "0x" + sel,
                }
            )
    return candidates


def main() -> int:
    url = os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")
    hits = scan_pending(url)
    out = ROOT / "artifacts" / "sandbox" / "mev-mempool-scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rpc": url, "candidates": hits}, indent=2) + "\n", encoding="utf-8")
    print(f"[scan] {len(hits)} swap candidates → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
