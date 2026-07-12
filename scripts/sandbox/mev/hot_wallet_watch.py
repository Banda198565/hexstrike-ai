#!/usr/bin/env python3
"""Watch hot wallet outgoing txs on BSC (read-only pending + recent blocks)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ART = ROOT / "artifacts" / "sandbox"
ALERTS = ART / "hot-wallet-alerts.jsonl"
STATE = ART / "hot-wallet-watch-state.json"

DEFAULT_WATCH = [
    "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA",
    "0xce648a7c1dd3dabc9cd2f87c93986a98608f1eef",
]
USDT = "0x55d398326f99059fF775485246999027B3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def rpc_urls() -> list[str]:
    urls = []
    for key in ("BSC_HTTP_URL", "BSC_HTTP_FALLBACK"):
        v = os.environ.get(key, "").strip()
        if v:
            urls.append(v)
    urls.append("https://bsc-dataseed.binance.org")
    return urls


def _rpc(url: str, method: str, params: list) -> any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        out = json.loads(resp.read())
    if out.get("error"):
        raise RuntimeError(out["error"])
    return out.get("result")


def pad_addr(a: str) -> str:
    return a.lower().replace("0x", "").zfill(64)


def classify_hit(hit: dict) -> str:
    t = hit.get("type", "")
    if t == "usdt_out":
        amt = hit.get("amount_usdt", 0)
        if amt >= 10000:
            return "large_usdt_out"
        if amt >= 1000:
            return "medium_usdt_out"
        return "small_usdt_out"
    if t == "native_pending":
        val = hit.get("value_wei", 0)
        if val >= 10**17:
            return "large_native_pending"
        return "native_pending"
    return "unknown"


def load_state() -> set[str]:
    if not STATE.is_file():
        return set()
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except Exception:
        return set()


def save_state(seen: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps({"seen": sorted(seen)[-500:], "ts": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )


def filter_delta(hits: list[dict], *, delta_only: bool) -> list[dict]:
    if not delta_only:
        return hits
    seen = load_state()
    new_hits: list[dict] = []
    for h in hits:
        key = h.get("tx") or h.get("hash") or json.dumps(h, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        h["classifier"] = classify_hit(h)
        new_hits.append(h)
    save_state(seen)
    return new_hits


def watch_addresses() -> list[str]:
    raw = os.environ.get("HOT_WALLET_WATCH", "")
    if raw.strip():
        return [a.strip() for a in raw.split(",") if a.strip().startswith("0x")]
    return DEFAULT_WATCH


def scan_outgoing_usdt(url: str, addr: str, blocks: int) -> list[dict]:
    latest = int(_rpc(url, "eth_blockNumber", []), 16)
    from_b = max(0, latest - blocks)
    topic_addr = "0x" + pad_addr(addr)
    logs = _rpc(
        url,
        "eth_getLogs",
        [{
            "fromBlock": hex(from_b),
            "toBlock": "latest",
            "address": USDT,
            "topics": [TRANSFER_TOPIC, topic_addr, None],
        }],
    )
    hits = []
    for lg in logs or []:
        to_addr = "0x" + lg["topics"][2][-40:]
        val = int(lg["data"], 16) / 1e18
        hits.append({
            "type": "usdt_out",
            "from": addr,
            "to": to_addr,
            "amount_usdt": round(val, 2),
            "tx": lg["transactionHash"],
            "block": int(lg["blockNumber"], 16),
        })
    return hits


def scan_pending_native(url: str, addr: str) -> list[dict]:
    """Best-effort: pending block txs from watch address."""
    hits = []
    try:
        block = _rpc(url, "eth_getBlockByNumber", ["pending", True])
    except Exception:
        return hits
    if not isinstance(block, dict):
        return hits
    watch = addr.lower()
    for tx in block.get("transactions") or []:
        if not isinstance(tx, dict):
            continue
        if (tx.get("from") or "").lower() != watch:
            continue
        hits.append({
            "type": "native_pending",
            "from": tx.get("from"),
            "to": tx.get("to"),
            "value_wei": int(tx.get("value", "0x0"), 16),
            "hash": tx.get("hash"),
            "gas_price_wei": int(tx.get("gasPrice", "0x0"), 16) if tx.get("gasPrice") else None,
        })
    return hits


def run_watch(*, once: bool = False) -> dict:
    blocks = int(os.environ.get("HOT_WATCH_BLOCK_DEPTH", "20"))
    polls = int(os.environ.get("HOT_WATCH_POLLS", "1" if once else "3"))
    interval = float(os.environ.get("HOT_WATCH_INTERVAL_SEC", "2"))

    all_alerts: list[dict] = []
    used_rpc = None
    for url in rpc_urls():
        try:
            if int(_rpc(url, "eth_chainId", []), 16) != 56:
                continue
            used_rpc = url
            for addr in watch_addresses():
                for hit in scan_outgoing_usdt(url, addr, blocks):
                    hit["ts"] = datetime.now(timezone.utc).isoformat()
                    hit["rpc"] = url
                    all_alerts.append(hit)
                for hit in scan_pending_native(url, addr):
                    hit["ts"] = datetime.now(timezone.utc).isoformat()
                    hit["rpc"] = url
                    all_alerts.append(hit)
            break
        except Exception:
            continue

    delta_only = os.environ.get("HOT_WATCH_DELTA", "0") == "1"
    for h in all_alerts:
        h["classifier"] = classify_hit(h)
    all_alerts = filter_delta(all_alerts, delta_only=delta_only)

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "rpc": used_rpc,
        "watch": watch_addresses(),
        "block_depth": blocks,
        "delta_only": delta_only,
        "alert_count": len(all_alerts),
        "alerts": all_alerts,
    }

    ART.mkdir(parents=True, exist_ok=True)
    out = ART / "hot-wallet-watch.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for a in all_alerts:
        with ALERTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(a) + "\n")

    if not once and polls > 1:
        for _ in range(polls - 1):
            time.sleep(interval)
            run_watch(once=True)

    return payload


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] hot_wallet_watch requires MEV_SANDBOX_ONLY=1", file=sys.stderr)
        return 1
    once = os.environ.get("HOT_WATCH_ONCE", "1") == "1"
    payload = run_watch(once=once)
    print(
        f"[watch] alerts={payload['alert_count']} rpc={payload['rpc']} "
        f"→ {ART / 'hot-wallet-watch.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
