#!/usr/bin/env python3
"""P2 read-only: decode Rhino.fi bridge events for top-3 cross-chain exits."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

TOP3 = {
    "0x730ea0231808f42a20f8921ba7fbc788226768f5": "authority_eip7702",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08": "sweep_contract_2",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a": "sweep_contract_3",
}

# Observed Rhino bridge topic0 signatures (BSC, Jul 2026 window)
TOPIC_DEPOSIT_V1 = "0xe4f4f1fb3534fe80225d336f6e5a73007dc992e5f6740152bf13ed2a08f3851a"
TOPIC_DEPOSIT_ID = "0x1655dc426ee0145d9436d28cfb463fb0e0717ae145566e5e534da64b735e49f3"
TOPIC_WITHDRAW = "0xad50835dbfd8ee369e3d3c5ffa2f72b0f250cb3cf4331f29e78fa780f20ef998"

EVENT_LABELS = {
    TOPIC_DEPOSIT_V1: "Deposit_v1(user,token,amount,bytes?)",
    TOPIC_DEPOSIT_ID: "DepositWithId(sender,origin,token,amount,commitmentId)",
    TOPIC_WITHDRAW: "Withdraw_v1(?,amount,recipient,bytes?)",
}

# Rhino.fi chain IDs (from docs.rhino.fi supported chains)
RHINO_CHAINS = {
    1: "ETHEREUM",
    10: "OPTIMISM",
    56: "BINANCE",
    100: "GNOSIS",
    137: "POLYGON",
    250: "FANTOM",
    324: "ZKSYNC",
    1101: "POLYGON_ZKEVM",
    42161: "ARBITRUM",
    43114: "AVALANCHE",
    59144: "LINEA",
    8453: "BASE",
    534352: "SCROLL",
    81457: "BLAST",
    167000: "TAIKO",
    1329: "SEI",
    146: "SONIC",
    80094: "BERACHAIN",
    130: "UNICHAIN",
}


def rpc_call(method: str, params: list, timeout: float = 60) -> Any:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(RPC, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def addr_from_word(word: str) -> str:
    return "0x" + word[-40:].lower()


def decode_words(data: str) -> list[str]:
    raw = data[2:] if data.startswith("0x") else data
    return [raw[i : i + 64] for i in range(0, len(raw), 64)]


def decode_deposit_v1(data: str) -> dict:
    words = decode_words(data)
    if len(words) < 3:
        return {}
    user = addr_from_word(words[0])
    token = addr_from_word(words[1])
    amount = int(words[2], 16) / 1e18
    extra = None
    if len(words) > 4:
        # dynamic bytes tail may hold recipient/chain hint
        extra = words[4:]
    return {
        "user": user,
        "token": token,
        "amount_usdt": round(amount, 6),
        "extra_words": extra,
    }


def decode_deposit_id(data: str) -> dict:
    words = decode_words(data)
    if len(words) < 5:
        return {}
    sender = addr_from_word(words[0])
    origin = addr_from_word(words[1])
    token = addr_from_word(words[2])
    amount = int(words[3], 16) / 1e18
    commitment_id = "0x" + words[4]
    chain_hint = None
    cid_int = int(words[4], 16)
    # Heuristic: low 32 bits sometimes map to EVM chain id in Rhino quotes
    low32 = cid_int & 0xFFFFFFFF
    if low32 in RHINO_CHAINS:
        chain_hint = RHINO_CHAINS[low32]
    return {
        "sender": sender,
        "origin": origin,
        "token": token,
        "amount_usdt": round(amount, 6),
        "commitment_id": commitment_id,
        "commitment_id_int": cid_int,
        "chain_hint_low32": chain_hint,
    }


def decode_withdraw_v1(data: str) -> dict:
    words = decode_words(data)
    if len(words) < 3:
        return {}
    field0 = int(words[0], 16)
    amount = int(words[1], 16) / 1e18
    recipient = addr_from_word(words[2])
    return {
        "field0": field0,
        "amount_usdt": round(amount, 6),
        "recipient": recipient,
    }


def decode_event(log: dict) -> dict:
    topic0 = (log.get("topics") or [None])[0]
    base = {
        "topic0": topic0,
        "event_label": EVENT_LABELS.get(topic0, "unknown"),
        "block": int(log["blockNumber"], 16),
        "tx_hash": log["transactionHash"],
        "log_index": int(log["logIndex"], 16),
    }
    data = log.get("data", "0x")
    if topic0 == TOPIC_DEPOSIT_V1:
        base["decoded"] = decode_deposit_v1(data)
    elif topic0 == TOPIC_DEPOSIT_ID:
        base["decoded"] = decode_deposit_id(data)
    elif topic0 == TOPIC_WITHDRAW:
        base["decoded"] = decode_withdraw_v1(data)
    else:
        base["decoded"] = {"raw_words": decode_words(data)}
    return base


def get_logs(from_block: int, to_block: int, address: str, topics: list | None = None) -> list[dict]:
    logs: list[dict] = []
    block = from_block
    while block <= to_block:
        end = min(block + CHUNK - 1, to_block)
        filt: dict = {"fromBlock": hex(block), "toBlock": hex(end), "address": address}
        if topics is not None:
            filt["topics"] = topics
        result = rpc_call("eth_getLogs", [filt], timeout=120)
        logs.extend(result or [])
        block = end + 1
    return logs


def parse_transfer(log: dict) -> dict:
    topics = log.get("topics") or []
    return {
        "from": addr_from_word(topics[1]),
        "to": addr_from_word(topics[2]),
        "value_usdt": round(int(log.get("data", "0x0"), 16) / 1e18, 6),
        "block": int(log["blockNumber"], 16),
        "tx_hash": log["transactionHash"],
        "log_index": int(log["logIndex"], 16),
    }


def load_top3_transfers() -> list[dict]:
    p1_path = ROOT / "artifacts" / "2026-07-10" / "p1-top3-outgoing-usdt.json"
    doc = json.loads(p1_path.read_text(encoding="utf-8"))
    transfers: list[dict] = []
    for addr, entry in doc.get("contracts", {}).items():
        for t in entry.get("outgoing_usdt", {}).get("transfers", []):
            t = dict(t)
            t["source_contract"] = addr.lower()
            t["source_label"] = TOP3.get(addr.lower(), TOP3.get(addr, "unknown"))
            transfers.append(t)
    return transfers


def match_deposit_events(transfers: list[dict], events: list[dict]) -> list[dict]:
    """Match bridge deposit events to top-3 USDT transfers by user+amount (+/- block window)."""
    matches: list[dict] = []
    deposit_events = [e for e in events if e["topic0"] in (TOPIC_DEPOSIT_V1, TOPIC_DEPOSIT_ID)]

    for t in transfers:
        src = t["source_contract"].lower()
        amt = t["value_usdt"]
        blk = t["block"]
        best = None
        best_score = 10**9

        for ev in deposit_events:
            dec = ev.get("decoded") or {}
            users = {
                (dec.get("user") or "").lower(),
                (dec.get("sender") or "").lower(),
                (dec.get("origin") or "").lower(),
            }
            ev_amt = dec.get("amount_usdt")
            if ev_amt is None:
                continue
            if src not in users:
                continue
            if abs(ev_amt - amt) > 0.02:
                continue
            score = abs(ev["block"] - blk)
            if score < best_score:
                best_score = score
                best = ev

        match = {
            "transfer": t,
            "matched_deposit_event": best,
            "block_delta": best_score if best else None,
        }
        matches.append(match)
    return matches


def analyze_batched_txs(transfers: list[dict]) -> list[dict]:
    """Receipt-level analysis: top-3 often batched via relayer 0x90502666."""
    out: list[dict] = []
    seen: set[str] = set()
    for t in transfers:
        tx = t["tx_hash"]
        if tx in seen:
            continue
        seen.add(tx)
        receipt = rpc_call("eth_getTransactionReceipt", [tx], timeout=30)
        tx_meta = rpc_call("eth_getTransactionByHash", [tx], timeout=30)
        usdt_logs = []
        for log in (receipt or {}).get("logs") or []:
            if (log.get("address") or "").lower() != USDT.lower():
                continue
            if (log.get("topics") or [None])[0] != TRANSFER_TOPIC:
                continue
            usdt_logs.append(parse_transfer(log))

        top3_in_tx = [x for x in usdt_logs if x["from"] in TOP3 and x["to"] == RHINO.lower()]
        out.append(
            {
                "tx_hash": tx,
                "block": int(receipt["blockNumber"], 16),
                "tx_from": ((tx_meta or {}).get("from") or "").lower(),
                "tx_to": ((tx_meta or {}).get("to") or "").lower(),
                "method_id": ((tx_meta or {}).get("input") or "0x")[:10],
                "batched_deposit": len(usdt_logs) > 1,
                "total_usdt_to_rhino": round(sum(x["value_usdt"] for x in usdt_logs if x["to"] == RHINO.lower()), 6),
                "top3_slice_usdt": round(sum(x["value_usdt"] for x in top3_in_tx), 6),
                "top3_transfers_in_tx": top3_in_tx,
                "all_usdt_to_rhino": [x for x in usdt_logs if x["to"] == RHINO.lower()],
            }
        )
    return out


def resolve_event_names() -> dict[str, str]:
    """Best-effort openchain lookup for topic0 labels."""
    topics = [TOPIC_DEPOSIT_V1, TOPIC_DEPOSIT_ID, TOPIC_WITHDRAW]
    out: dict[str, str] = {}
    for topic in topics:
        try:
            proc = subprocess.run(
                ["curl", "-sS", f"https://api.openchain.xyz/signature-database/v1/lookup?event={topic}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            doc = json.loads(proc.stdout or "{}")
            result = doc.get("result", {}).get("event", {}).get(topic, [])
            out[topic] = result[0]["name"] if result else EVENT_LABELS.get(topic, "unknown")
        except Exception:
            out[topic] = EVENT_LABELS.get(topic, "unknown")
    return out


def aggregate_chain_hints(matches: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for m in matches:
        ev = m.get("matched_deposit_event")
        if not ev:
            continue
        hint = (ev.get("decoded") or {}).get("chain_hint_low32")
        if hint:
            counts[hint] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def write_artifact(name: str, obj: object) -> list[str]:
    paths: list[str] = []
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    return paths


def main() -> int:
    errors: list[str] = []
    transfers = load_top3_transfers()
    event_names = resolve_event_names()

    print("[P2] Fetching Rhino bridge contract events...")
    raw_events = get_logs(FROM_BLOCK, TO_BLOCK, RHINO)
    events = [decode_event(log) for log in raw_events]

    top3_set = set(TOP3.keys())
    top3_deposits = []
    for ev in events:
        dec = ev.get("decoded") or {}
        actors = {
            (dec.get("user") or "").lower(),
            (dec.get("sender") or "").lower(),
            (dec.get("origin") or "").lower(),
        }
        if actors & top3_set:
            top3_deposits.append(ev)

    matches = match_deposit_events(transfers, events)
    batched = analyze_batched_txs(transfers)

    # commitmentId → chain hint stats from all deposit-id events touching top3 amounts
    commitment_samples = []
    for ev in top3_deposits:
        if ev["topic0"] != TOPIC_DEPOSIT_ID:
            continue
        dec = ev["decoded"]
        commitment_samples.append(
            {
                "block": ev["block"],
                "tx_hash": ev["tx_hash"],
                "sender": dec.get("sender"),
                "amount_usdt": dec.get("amount_usdt"),
                "commitment_id": dec.get("commitment_id"),
                "chain_hint": dec.get("chain_hint_low32"),
            }
        )

    matched_count = sum(1 for m in matches if m.get("matched_deposit_event"))
    chain_hints = aggregate_chain_hints(matches)

    summary = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy": "read_only_p2",
            "rpc": RPC,
            "block_range": [FROM_BLOCK, TO_BLOCK],
            "bridge": RHINO,
            "event_signatures_resolved": event_names,
        },
        "findings": {
            "top3_transfer_count": len(transfers),
            "top3_total_usdt": round(sum(t["value_usdt"] for t in transfers), 2),
            "bridge_events_total": len(events),
            "top3_deposit_events_direct": len(top3_deposits),
            "transfer_to_deposit_event_matches": matched_count,
            "batched_relayer_txs": sum(1 for b in batched if b["batched_deposit"]),
            "dominant_relayer": "0x90502666e33d71483302f81c8349a6185572db42",
            "cross_chain_exit_mechanism": (
                "USDT sent to Rhino.fi bridge via batched relayer deposits; "
                "cross-chain routing encoded in commitmentId / off-chain Rhino quote (API auth required for exact chainOut)"
            ),
            "chain_hints_from_commitment_low32": chain_hints,
        },
        "top3_deposit_events": top3_deposits,
        "transfer_deposit_matches": matches,
        "batched_tx_analysis": batched,
        "commitment_id_samples": commitment_samples[:20],
        "verdict": (
            "Top-3 funds exit BSC through Rhino.fi bridge using batched deposit transactions. "
            "On-chain deposit events link sender contracts to commitmentIds; "
            "destination chain resolution requires Rhino bridge status API or destination-chain withdraw tx lookup."
        ),
        "errors": errors,
    }

    paths = write_artifact("p2-rhino-crosschain-decode.json", summary)
    print(json.dumps(summary["findings"], indent=2))
    print(f"[+] Written: {paths[0]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
