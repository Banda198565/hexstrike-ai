#!/usr/bin/env python3
"""Mempool scanner — classifies pending swaps for offensive MEV pipeline (read-only RPC)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fork_mempool import PANCAKE_ROUTER, scan_mempool, seed_pending_swaps

ROOT = Path(__file__).resolve().parents[3]


def _chain_id(url: str) -> int | None:
    try:
        from fork_mempool import _rpc

        raw = _rpc("eth_chainId", [])
        return int(raw, 16) if isinstance(raw, str) else int(raw)
    except Exception:
        return None


def main() -> int:
    url = os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")
    chain_id = _chain_id(url)

    if os.environ.get("FORK_SEED_MEMPOOL") == "1" and chain_id == 56:
        n = int(os.environ.get("FORK_SEED_COUNT", "3"))
        hashes = seed_pending_swaps(n)
        print(f"[seed] queued {len(hashes)} Pancake swaps on BSC fork")

    payload = scan_mempool(url, chain_id=chain_id)
    payload["chain_id"] = chain_id
    if chain_id == 56:
        payload.setdefault("router_filter", PANCAKE_ROUTER)

    out_name = (
        "mev-bsc-mempool-scan.json"
        if chain_id == 56
        else "mev-mempool-scan.json"
    )
    out = ROOT / "artifacts" / "sandbox" / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    candidates = [c for c in payload.get("candidates", []) if not c.get("error")]
    print(f"[scan] chain={chain_id} {len(candidates)} swap candidates → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
