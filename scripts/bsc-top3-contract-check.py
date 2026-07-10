#!/usr/bin/env python3
"""Read-only BSC check: contract vs EOA + incoming USDT transfers for top-3 addresses."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "artifacts" / "2026-07-10"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RPC = "https://bsc-dataseed.binance.org/"
USDT_BSC = "0x55d398326f99059fF775485246999027B3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

TOP_3 = [
    "0x730ea0231808f42a20f8921ba7fbc788226768f5",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a",
]

# ~last 500k blocks on BSC public RPC (avoid timeout)
FROM_BLOCK = 0x1C9C380  # fallback; updated dynamically below


def rpc_call(method: str, params: list, timeout: float = 15) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(RPC, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def is_contract(address: str) -> bool:
    data = rpc_call("eth_getCode", [address, "latest"], timeout=10)
    code = data.get("result", "0x")
    return code not in ("0x", "0x0") and len(code) > 2


def get_balance_bnb(address: str) -> float:
    data = rpc_call("eth_getBalance", [address, "latest"], timeout=10)
    bal = data.get("result", "0x0")
    return round(int(bal, 16) / 1e18, 6) if bal and bal != "0x" else 0.0


def get_incoming_transfers(address: str, from_block: int, limit: int = 10) -> tuple[list[dict], str | None]:
    addr = address.lower()
    addr_topic = "0x" + "0" * 24 + addr[2:]
    chunk = 20_000
    latest_data = rpc_call("eth_blockNumber", [])
    latest = int(latest_data["result"], 16)
    start = max(from_block, latest - 100_000)

    all_logs: list[dict] = []
    err_msg: str | None = None

    block = start
    while block <= latest and len(all_logs) < limit:
        to_block = min(block + chunk - 1, latest)
        try:
            params = [{
                "fromBlock": hex(block),
                "toBlock": hex(to_block),
                "address": USDT_BSC,
                "topics": [TRANSFER_TOPIC, None, addr_topic],
            }]
            data = rpc_call("eth_getLogs", params, timeout=30)
            logs = data.get("result") or []
            if isinstance(logs, list):
                all_logs.extend(logs)
        except Exception as exc:
            err_msg = str(exc)
            break
        block = to_block + 1

    transfers: list[dict] = []
    for log in all_logs[:limit]:
        topics = log.get("topics") or []
        from_raw = topics[1] if len(topics) > 1 else ""
        from_addr = ("0x" + from_raw[-40:]) if from_raw else ""
        value_raw = log.get("data", "0x0")
        value = int(value_raw, 16) / 1e18 if value_raw and value_raw != "0x" else 0.0
        transfers.append({
            "from": from_addr,
            "value_usdt": round(value, 2),
            "block": int(log.get("blockNumber", "0x0"), 16),
            "tx_hash": log.get("transactionHash"),
        })
    return transfers, err_msg


def main() -> int:
    # Dynamic from_block: latest - 500k
    latest = int(rpc_call("eth_blockNumber", [])["result"], 16)
    from_block = max(0, latest - 500_000)

    simple = []
    detailed: dict[str, dict] = {}

    for addr in TOP_3:
        contract = is_contract(addr)
        bnb = get_balance_bnb(addr)
        typ = "CONTRACT" if contract else "EOA"

        simple.append({"addr": addr, "type": typ, "bnb": bnb})

        try:
            incoming, err = get_incoming_transfers(addr, from_block, limit=10)
        except Exception as exc:
            incoming = []
            err = str(exc)

        detailed[addr] = {
            "is_contract": contract,
            "type": "contract" if contract else "EOA",
            "bnb_balance": bnb,
            "from_block": from_block,
            "latest_block": latest,
            "incoming_count_sampled": len(incoming),
            "sample": incoming,
        }
        if err:
            detailed[addr]["error"] = err

        print(f"{addr} | {typ} | {bnb} BNB | incoming USDT (sample): {len(incoming)}")
        for t in incoming[:3]:
            print(f"  <- {t['from']}: {t['value_usdt']:,.2f} USDT (block {t['block']})")
        if err:
            print(f"  error: {err}")

    ts = datetime.now(tz=timezone.utc).isoformat()
    meta = {"timestamp": ts, "rpc": RPC, "chain": "bsc", "policy": "read_only"}

    final_path = OUT_DIR / "top3-final-check.json"
    contract_path = OUT_DIR / "top3-contract-check.json"

    final_path.write_text(json.dumps({"meta": meta, "results": simple}, indent=2) + "\n", encoding="utf-8")
    contract_path.write_text(json.dumps({"meta": meta, "results": detailed}, indent=2) + "\n", encoding="utf-8")

    print(f"\nSaved: {final_path}")
    print(f"Saved: {contract_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
