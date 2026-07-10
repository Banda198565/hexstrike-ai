#!/usr/bin/env python3
"""Read-only BSC depth-3 forensics: Rhino.fi bridge (P0) + top-3 outgoing USDT (P1)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [
    ROOT / "artifacts" / "2026-07-10",
    Path.home() / "Desktop" / "on-chain-forensics" / "artifacts" / "2026-07-10",
]

RPC = "http://51.222.42.220:8545"
FROM_BLOCK = 108941522
TO_BLOCK = 109041522
CHUNK = 5000

USDT = "0x55d398326f99059fF775485246999027B3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
RHINO = "0xb80a582fa430645a043bb4f6135321ee01005fef"

TOP3 = [
    "0x730ea0231808f42a20f8921ba7fbc788226768f5",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a",
]


def addr_topic(address: str) -> str:
    return "0x" + "0" * 24 + address.lower().replace("0x", "")


def rpc_call(method: str, params: list, timeout: float = 60) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(RPC, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def iter_block_ranges(start: int, end: int, chunk: int):
    block = start
    while block <= end:
        to_block = min(block + chunk - 1, end)
        yield block, to_block
        block = to_block + 1


def get_logs(
    from_block: int,
    to_block: int,
    address: str | None = None,
    topics: list | None = None,
) -> tuple[list[dict], list[str]]:
    logs: list[dict] = []
    errors: list[str] = []
    for start, end in iter_block_ranges(from_block, to_block, CHUNK):
        filt: dict = {"fromBlock": hex(start), "toBlock": hex(end)}
        if address is not None:
            filt["address"] = address
        if topics is not None:
            filt["topics"] = topics
        try:
            data = rpc_call("eth_getLogs", [filt], timeout=120)
            chunk_logs = data.get("result") or []
            if isinstance(chunk_logs, list):
                logs.extend(chunk_logs)
        except Exception as exc:
            errors.append(f"blocks {start}-{end}: {exc}")
    return logs, errors


def parse_transfer(log: dict) -> dict:
    topics = log.get("topics") or []
    from_raw = topics[1] if len(topics) > 1 else ""
    to_raw = topics[2] if len(topics) > 2 else ""
    from_addr = ("0x" + from_raw[-40:]).lower() if from_raw else ""
    to_addr = ("0x" + to_raw[-40:]).lower() if to_raw else ""
    value_raw = log.get("data", "0x0")
    value = int(value_raw, 16) / 1e18 if value_raw and value_raw != "0x" else 0.0
    return {
        "from": from_addr,
        "to": to_addr,
        "value_usdt": round(value, 6),
        "block": int(log.get("blockNumber", "0x0"), 16),
        "tx_hash": log.get("transactionHash"),
        "log_index": int(log.get("logIndex", "0x0"), 16),
    }


def normalize_event(log: dict) -> dict:
    topics = log.get("topics") or []
    return {
        "address": (log.get("address") or "").lower(),
        "topics": topics,
        "topic0": topics[0] if topics else None,
        "data": log.get("data"),
        "block": int(log.get("blockNumber", "0x0"), 16),
        "tx_hash": log.get("transactionHash"),
        "log_index": int(log.get("logIndex", "0x0"), 16),
    }


def dedupe_logs(logs: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for log in logs:
        key = (
            log.get("transactionHash"),
            log.get("logIndex"),
            log.get("blockNumber"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(log)
    return out


def summarize_transfers(transfers: list[dict]) -> dict:
    total = sum(t["value_usdt"] for t in transfers)
    by_from: dict[str, float] = defaultdict(float)
    by_to: dict[str, float] = defaultdict(float)
    for t in transfers:
        by_from[t["from"]] += t["value_usdt"]
        by_to[t["to"]] += t["value_usdt"]
    top_from = sorted(by_from.items(), key=lambda x: x[1], reverse=True)[:10]
    top_to = sorted(by_to.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "count": len(transfers),
        "total_usdt": round(total, 6),
        "unique_senders": len(by_from),
        "unique_recipients": len(by_to),
        "top_senders": [{"address": a, "usdt": round(v, 6)} for a, v in top_from],
        "top_recipients": [{"address": a, "usdt": round(v, 6)} for a, v in top_to],
    }


def summarize_events(events: list[dict]) -> dict:
    by_topic: dict[str, int] = defaultdict(int)
    for e in events:
        t0 = e.get("topic0") or "none"
        by_topic[t0] += 1
    return {
        "count": len(events),
        "unique_topic0": len(by_topic),
        "topic0_counts": dict(sorted(by_topic.items(), key=lambda x: x[1], reverse=True)),
    }


def write_artifact(name: str, obj: object) -> list[str]:
    paths: list[str] = []
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    return paths


def run_p0(errors: list[str]) -> dict:
    rhino_topic = addr_topic(RHINO)

    incoming_raw, incoming_errs = get_logs(
        FROM_BLOCK,
        TO_BLOCK,
        address=USDT,
        topics=[TRANSFER_TOPIC, None, rhino_topic],
    )
    errors.extend(incoming_errs)
    incoming_raw = dedupe_logs(incoming_raw)
    incoming = [parse_transfer(log) for log in incoming_raw]
    incoming.sort(key=lambda x: (x["block"], x["log_index"]))

    events_raw, events_errs = get_logs(
        FROM_BLOCK,
        TO_BLOCK,
        address=RHINO,
        topics=None,
    )
    errors.extend(events_errs)
    events_raw = dedupe_logs(events_raw)
    events = [normalize_event(log) for log in events_raw]
    events.sort(key=lambda x: (x["block"], x["log_index"]))

    p0_detail = {
        "target": RHINO,
        "label": "Rhino.fi Bridge",
        "block_range": {"from": FROM_BLOCK, "to": TO_BLOCK},
        "incoming_usdt": {
            "summary": summarize_transfers(incoming),
            "transfers": incoming,
        },
        "contract_events": {
            "summary": summarize_events(events),
            "events": events,
        },
    }

    paths = write_artifact("p0-rhino-bridge-trace.json", p0_detail)
    return {
        "artifact": paths[0],
        "artifact_paths": paths,
        "incoming_usdt": p0_detail["incoming_usdt"]["summary"],
        "contract_events": p0_detail["contract_events"]["summary"],
    }


def run_p1(errors: list[str]) -> dict:
    results: dict[str, dict] = {}
    aggregate_outgoing: list[dict] = []

    for addr in TOP3:
        src_topic = addr_topic(addr)
        outgoing_raw, outgoing_errs = get_logs(
            FROM_BLOCK,
            TO_BLOCK,
            address=USDT,
            topics=[TRANSFER_TOPIC, src_topic, None],
        )
        errors.extend(outgoing_errs)
        outgoing_raw = dedupe_logs(outgoing_raw)
        outgoing = [parse_transfer(log) for log in outgoing_raw]
        outgoing.sort(key=lambda x: (x["block"], x["log_index"]))
        aggregate_outgoing.extend(outgoing)

        results[addr.lower()] = {
            "address": addr.lower(),
            "outgoing_usdt": {
                "summary": summarize_transfers(outgoing),
                "transfers": outgoing,
            },
        }

    p1_detail = {
        "block_range": {"from": FROM_BLOCK, "to": TO_BLOCK},
        "contracts": results,
        "aggregate_outgoing_usdt": summarize_transfers(aggregate_outgoing),
    }

    paths = write_artifact("p1-top3-outgoing-usdt.json", p1_detail)
    return {
        "artifact": paths[0],
        "artifact_paths": paths,
        "per_contract": {
            addr: results[addr.lower()]["outgoing_usdt"]["summary"]
            for addr in TOP3
        },
        "aggregate": p1_detail["aggregate_outgoing_usdt"],
    }


def main() -> int:
    errors: list[str] = []
    ts = datetime.now(tz=timezone.utc).isoformat()

    print(f"[*] BSC depth-3 trace | RPC={RPC}")
    print(f"[*] Block range: {FROM_BLOCK} -> {TO_BLOCK} (chunk={CHUNK})")

    try:
        latest = int(rpc_call("eth_blockNumber", [])["result"], 16)
    except Exception as exc:
        latest = None
        errors.append(f"eth_blockNumber: {exc}")

    print("[*] P0: Rhino.fi bridge incoming USDT + contract events...")
    p0 = run_p0(errors)
    print(
        f"    incoming USDT: {p0['incoming_usdt']['count']} transfers, "
        f"{p0['incoming_usdt']['total_usdt']:,.2f} USDT"
    )
    print(
        f"    contract events: {p0['contract_events']['count']} logs, "
        f"{p0['contract_events']['unique_topic0']} topic0 variants"
    )

    print("[*] P1: Top-3 outgoing USDT...")
    p1 = run_p1(errors)
    for addr in TOP3:
        s = p1["per_contract"][addr.lower()]
        print(f"    {addr}: {s['count']} transfers, {s['total_usdt']:,.2f} USDT")
    print(
        f"    aggregate: {p1['aggregate']['count']} transfers, "
        f"{p1['aggregate']['total_usdt']:,.2f} USDT"
    )

    summary = {
        "meta": {
            "timestamp": ts,
            "rpc": RPC,
            "chain": "bsc",
            "policy": "read_only",
            "block_range": {"from": FROM_BLOCK, "to": TO_BLOCK, "chunk_size": CHUNK},
            "latest_block_seen": latest,
            "usdt": USDT,
            "transfer_topic": TRANSFER_TOPIC,
        },
        "p0_rhino_bridge": {
            "address": RHINO,
            "incoming_usdt": p0["incoming_usdt"],
            "contract_events": p0["contract_events"],
            "artifact": p0["artifact"],
            "artifact_paths": p0["artifact_paths"],
        },
        "p1_top3_outgoing_usdt": {
            "contracts": TOP3,
            "per_contract": p1["per_contract"],
            "aggregate": p1["aggregate"],
            "artifact": p1["artifact"],
            "artifact_paths": p1["artifact_paths"],
        },
        "errors": errors,
    }

    summary_paths = write_artifact("bsc-depth3-trace-summary.json", summary)
    summary["summary_artifact"] = summary_paths[0]
    summary["summary_artifact_paths"] = summary_paths

    print(f"\n[+] Summary: {summary_paths[0]}")
    if errors:
        print(f"[!] {len(errors)} chunk error(s) recorded in summary.errors")
        for e in errors[:5]:
            print(f"    - {e}")

    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
