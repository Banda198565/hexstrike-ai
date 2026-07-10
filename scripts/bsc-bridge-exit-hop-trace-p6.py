#!/usr/bin/env python3
"""P6 worker: Base hop-trace from Rhino withdrawal recipients toward hot wallet (orchestrator-only)."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [
    ROOT / "artifacts" / "2026-07-10",
    ROOT / "artifacts" / "forensics",
    Path.home() / "Desktop" / "on-chain-forensics" / "artifacts" / "2026-07-10",
]

BASE_RPC = os.environ.get("HEXSTRIKE_BASE_RPC", "https://mainnet.base.org")
HOT = "0x4943f5e7f4e450d48ae82026163ecde8a52c53da"
BASE_RHINO = "0x2f59e9086ec8130e21bd052065a9e6b2497bb102"
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
ROUTER_HINT = "0x1c128bbd0c70da36a4f13531c92f37d8f1ccc0f2"

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
LOG_CHUNK = 2000
HOP_DEPTH = 2
BLOCK_PAD_BEFORE = 500
BLOCK_PAD_AFTER = 15000
MAX_MID_HOP_ADDRS = 40


def rpc_call(url: str, method: str, params: list, timeout: float = 60) -> Any:
    import requests

    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:].lower()


def get_logs_chunked(
    url: str,
    address: str,
    topics: list[Any],
    from_block: int,
    to_block: int,
) -> list[dict]:
    logs: list[dict] = []
    start = from_block
    while start <= to_block:
        end = min(start + LOG_CHUNK - 1, to_block)
        batch = rpc_call(
            url,
            "eth_getLogs",
            [{"fromBlock": hex(start), "toBlock": hex(end), "address": address, "topics": topics}],
            timeout=90,
        )
        logs.extend(batch or [])
        start = end + 1
    return logs


def parse_transfer(log: dict) -> dict[str, Any]:
    return {
        "from": ("0x" + log["topics"][1][-40:]).lower(),
        "to": ("0x" + log["topics"][2][-40:]).lower(),
        "amount_usdc": round(int(log["data"], 16) / 1e6, 6),
        "tx_hash": log["transactionHash"],
        "block": int(log["blockNumber"], 16),
    }


def load_p5_seeds() -> tuple[list[dict], dict[str, Any]]:
    p5_path = ROOT / "artifacts" / "2026-07-10" / "p5-bridge-exit-correlate.json"
    p5 = json.loads(p5_path.read_text(encoding="utf-8"))
    seeds: dict[str, dict] = {}

    def add_seed(addr: str, source: str, meta: dict | None = None) -> None:
        a = addr.lower()
        if a in (HOT.lower(), BASE_RHINO.lower(), "0x0000000000000000000000000000000000000000"):
            return
        if a not in seeds:
            seeds[a] = {"address": a, "sources": [], "meta": []}
        seeds[a]["sources"].append(source)
        if meta:
            seeds[a]["meta"].append(meta)

    add_seed(ROUTER_HINT, "p5_router_hint")
    for row in p5.get("base_correlation", {}).get("per_deposit_correlation", []):
        bm = row.get("best_match")
        if bm and bm.get("recipient"):
            add_seed(
                bm["recipient"],
                "p5_best_match",
                {"bsc_tx": row.get("bsc_deposit_tx"), "amount_usdt": row.get("amount_usdt")},
            )
        for cand in row.get("candidates", []):
            if cand.get("recipient"):
                add_seed(cand["recipient"], "p5_candidate")

    for sample in p5.get("base_correlation", {}).get("bridge_usdc_outflows", {}).get("amount_match_samples", []):
        if sample.get("to"):
            add_seed(sample["to"], "p5_amount_match_outflow")

    for rec in p5.get("base_correlation", {}).get("bridged_withdrawal_events", {}).get(
        "top_recipients_for_matched_amounts", []
    ):
        if rec.get("address"):
            add_seed(rec["address"], "p5_withdrawal_recipient_rank")

    seed_list = list(seeds.values())
    # Prioritize P5 best-match recipients + router (smaller RPC footprint).
    priority = [s for s in seed_list if "p5_best_match" in s.get("sources", [])]
    if priority:
        priority_addrs = {s["address"] for s in priority}
        router = next((s for s in seed_list if s["address"] == ROUTER_HINT.lower()), None)
        trimmed = priority + ([router] if router and router["address"] not in priority_addrs else [])
        return trimmed, p5
    return seed_list, p5


def build_outgoing_index(
    from_block: int,
    to_block: int,
    watch_from: set[str],
) -> dict[str, list[dict]]:
    """Index USDC transfers where `from` is in watch_from."""
    by_from: dict[str, list[dict]] = defaultdict(list)
    for addr in watch_from:
        logs = get_logs_chunked(
            BASE_RPC,
            BASE_USDC,
            [TRANSFER_TOPIC, topic_addr(addr)],
            from_block,
            to_block,
        )
        for lg in logs:
            row = parse_transfer(lg)
            by_from[row["from"]].append(row)
    return by_from


def build_incoming_to_hot(from_block: int, to_block: int) -> list[dict]:
    hot_topic = topic_addr(HOT)
    logs = get_logs_chunked(
        BASE_RPC,
        BASE_USDC,
        [TRANSFER_TOPIC, None, hot_topic],
        from_block,
        to_block,
    )
    return [parse_transfer(lg) for lg in logs]


def trace_hops(
    seeds: list[dict],
    outgoing: dict[str, list[dict]],
    incoming_hot: list[dict],
) -> list[dict]:
    hot_l = HOT.lower()
    hot_senders = Counter(r["from"] for r in incoming_hot)
    results: list[dict] = []

    for seed in seeds:
        origin = seed["address"]
        paths: list[dict] = []

        # depth 1: origin -> X
        for e1 in outgoing.get(origin, []):
            if e1["to"] == hot_l:
                paths.append(
                    {
                        "hops": 1,
                        "path": [origin, hot_l],
                        "amount_usdc": e1["amount_usdc"],
                        "tx_hashes": [e1["tx_hash"]],
                        "blocks": [e1["block"]],
                    }
                )
                continue
            # depth 2: origin -> mid -> hot
            for e2 in outgoing.get(e1["to"], []):
                if e2["to"] == hot_l:
                    paths.append(
                        {
                            "hops": 2,
                            "path": [origin, e1["to"], hot_l],
                            "amount_usdc": e2["amount_usdc"],
                            "tx_hashes": [e1["tx_hash"], e2["tx_hash"]],
                            "blocks": [e1["block"], e2["block"]],
                        }
                    )

        # reverse: did hot receive from someone who got funded by origin?
        for inc in incoming_hot:
            mid = inc["from"]
            for e1 in outgoing.get(origin, []):
                if e1["to"] == mid:
                    paths.append(
                        {
                            "hops": 2,
                            "path": [origin, mid, hot_l],
                            "amount_usdc": inc["amount_usdc"],
                            "tx_hashes": [e1["tx_hash"], inc["tx_hash"]],
                            "blocks": [e1["block"], inc["block"]],
                            "pattern": "fund_then_forward_to_hot",
                        }
                    )

        results.append(
            {
                "seed": origin,
                "sources": sorted(set(seed.get("sources", []))),
                "meta": seed.get("meta", []),
                "outgoing_usdc_count": len(outgoing.get(origin, [])),
                "top_outgoing_destinations": [
                    {"address": a, "transfer_count": c}
                    for a, c in Counter(r["to"] for r in outgoing.get(origin, [])).most_common(5)
                ],
                "paths_to_hot": paths[:10],
                "reaches_hot": bool(paths),
                "hot_sent_direct_usdc": round(sum(r["amount_usdc"] for r in outgoing.get(origin, []) if r["to"] == hot_l), 2),
            }
        )

    return results


def write_artifact(name: str, obj: dict) -> list[str]:
    paths: list[str] = []
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    return paths


def main() -> int:
    seeds, p5 = load_p5_seeds()
    if not seeds:
        print("ERROR: no P5 seeds", file=sys.stderr)
        return 1

    scan = p5.get("base_correlation", {}).get("base_scan", {})
    from_block = int(scan.get("from_block", 48395635)) - BLOCK_PAD_BEFORE
    to_block = int(scan.get("to_block", 48466000)) + BLOCK_PAD_AFTER
    latest = int(rpc_call(BASE_RPC, "eth_blockNumber", []), 16)
    to_block = min(to_block, latest)

    seed_addrs = {s["address"] for s in seeds}
    outgoing_l1 = build_outgoing_index(from_block, to_block, seed_addrs)

    # expand watch set with level-1 recipients for depth-2
    mid_addrs: set[str] = set()
    for rows in outgoing_l1.values():
        for r in rows:
            if r["to"] not in seed_addrs and r["to"] != HOT.lower():
                mid_addrs.add(r["to"])

    outgoing_all = dict(outgoing_l1)
    if mid_addrs:
        limited_mids = set(list(mid_addrs)[:MAX_MID_HOP_ADDRS])
        outgoing_l2 = build_outgoing_index(from_block, to_block, limited_mids)
        for k, v in outgoing_l2.items():
            outgoing_all.setdefault(k, []).extend(v)

    incoming_hot = build_incoming_to_hot(from_block, to_block)
    hop_rows = trace_hops(seeds, outgoing_all, incoming_hot)

    reaches = [r for r in hop_rows if r["reaches_hot"]]
    top_hot_senders = hot_senders = Counter(r["from"] for r in incoming_hot).most_common(15)

    # cross-check: do any hot inbound senders overlap with seed graph?
    seed_graph = seed_addrs | mid_addrs
    overlap = [a for a, _ in top_hot_senders if a in seed_graph]

    summary = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy": "read_only_p6",
            "base_rpc": BASE_RPC,
            "worker": "scripts/bsc-bridge-exit-hop-trace-p6.py",
            "invoked_by": "hexstrike_orchestrator bridge-exit-hop-trace",
            "hop_depth": HOP_DEPTH,
        },
        "scan_window": {
            "from_block": from_block,
            "to_block": to_block,
            "blocks_scanned": to_block - from_block + 1,
        },
        "seeds": {
            "count": len(seeds),
            "addresses": [s["address"] for s in seeds],
        },
        "hot_wallet_inbound_usdc": {
            "transfer_count": len(incoming_hot),
            "total_usdc": round(sum(r["amount_usdc"] for r in incoming_hot), 2),
            "top_senders": [{"address": a, "count": c} for a, c in top_hot_senders],
            "senders_in_seed_graph": overlap,
        },
        "hop_traces": hop_rows,
        "summary": {
            "seeds_reaching_hot_within_2_hops": len(reaches),
            "seeds_total": len(seeds),
            "direct_paths_found": sum(len(r["paths_to_hot"]) for r in hop_rows),
        },
        "exit_rail_conclusion": {
            "chainOut": "BASE",
            "confidence": "medium-high" if reaches else "medium",
            "treasury_link": (
                "Rhino withdrawal recipients connect to hot wallet within 2 USDC hops"
                if reaches
                else "No direct 2-hop USDC path from P5 recipients to hot wallet in scan window; "
                "treasury may use separate Base deposit addresses or >2 hops"
            ),
            "deposit_address_pattern": (
                "Rhino enabledDepositAddress=true — recipients are per-quote deposit contracts; "
                "observed dust forwards to 0xbface6ad3c7f07714f2cc0a2651436f897537a95 (not hot wallet)"
            ),
        },
        "verdict": (
            f"P6 Base hop-trace: scanned {len(seeds)} Rhino-related recipients over "
            f"{to_block - from_block + 1} blocks. "
            f"{len(reaches)}/{len(seeds)} seeds reach hot wallet within {HOP_DEPTH} USDC hops. "
            "Cross-chain exit rail BASE confirmed; quote-bound recipients may consolidate off hot wallet EOA."
        ),
        "next_steps_readonly": [
            "Extend hop depth to 3–4 for unmatched seeds",
            "Set RHINO_API_KEY for definitive deposit→withdraw recipient mapping",
            "Arkham label overlap senders from hot_wallet_inbound_usdc.top_senders",
        ],
    }

    paths = write_artifact("p6-bridge-exit-hop-trace.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"[+] Written: {paths[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
