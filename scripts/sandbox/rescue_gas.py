#!/usr/bin/env python3
"""SAFE → GAS_HOLDER gas rescue (BSC/mainnet). Read-only checks + optional broadcast."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "artifacts" / "sandbox" / "rescue-operations.jsonl"


def rpc(url: str, method: str, params: list) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data["result"]


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def append_log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def daily_rescue_total(hours: int = 24) -> int:
    """Sum rescue_wei from successful sends in the last N hours."""
    if not LOG.is_file():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = 0
    for line in LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("action") != "rescue_sent":
            continue
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if ts >= cutoff:
            total += int(row.get("rescue_wei", 0))
    return total


def pending_count(holder: str, rpc_url: str) -> int:
    """Nonce gap heuristic: pending = latest - confirmed."""
    latest = int(rpc(rpc_url, "eth_getTransactionCount", [holder, "latest"]), 16)
    pending = int(rpc(rpc_url, "eth_getTransactionCount", [holder, "pending"]), 16)
    return max(0, pending - latest)


def send_gas_cast(holder: str, value_wei: int, rpc_url: str, safe_key: str, chain_id: int) -> str:
    import subprocess

    cmd = [
        "cast", "send", holder,
        "--value", str(value_wei),
        "--rpc-url", rpc_url,
        "--private-key", safe_key,
        "--chain-id", str(chain_id),
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    try:
        payload = json.loads(proc.stdout)
        return payload.get("transactionHash") or payload.get("hash") or proc.stdout.strip()
    except json.JSONDecodeError:
        return proc.stdout.strip()


def main() -> int:
    env_path = Path(os.environ.get("SANDBOX_ENV", ROOT / ".env"))
    load_env(env_path)

    rpc_url = os.environ.get("RPC_URL", "https://bsc-dataseed.binance.org")
    chain_id = int(os.environ.get("CHAIN_ID", "56"))
    holder = os.environ.get("GAS_HOLDER_ADDRESS") or os.environ.get("BOT_ADDRESS", "")
    safe_key = os.environ.get("SAFE_PRIVATE_KEY") or os.environ.get("SAFE_KEY", "")
    safe_addr = os.environ.get("SAFE_ADDRESS") or os.environ.get("FUNDER_ADDRESS", "")
    min_gas = int(os.environ.get("MIN_GAS_WEI", "10000000000000000"))
    rescue_wei = int(os.environ.get("RESCUE_GAS_WEI", os.environ.get("RESCUE_VALUE_WEI", "10000000000000000")))
    daily_limit = int(os.environ.get("RESCUE_DAILY_LIMIT_WEI", "500000000000000000"))
    dry = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")
    force = "--force" in sys.argv

    if not holder:
        print("[rescue] FAIL: GAS_HOLDER_ADDRESS or BOT_ADDRESS required", file=sys.stderr)
        return 1

    bal = int(rpc(rpc_url, "eth_getBalance", [holder, "latest"]), 16)
    pend = pending_count(holder, rpc_url)
    need = bal < min_gas or pend > 0

    spent_24h = daily_rescue_total()
    remaining = max(0, daily_limit - spent_24h)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "initiator": "signing-bot-rescue",
        "gas_holder": holder,
        "safe": safe_addr,
        "balance_wei": bal,
        "pending_gap": pend,
        "min_gas_wei": min_gas,
        "rescue_wei": rescue_wei,
        "daily_limit_wei": daily_limit,
        "daily_spent_wei": spent_24h,
        "daily_remaining_wei": remaining,
        "dry_run": dry,
    }

    if not need and not force:
        entry["action"] = "skip"
        entry["reason"] = "balance OK and no pending gap"
        append_log(entry)
        print(json.dumps({"success": True, "action": "skip", **entry}, indent=2))
        return 0

    if dry:
        entry["action"] = "dry_run"
        entry["tx_hash"] = "skipped DRY_RUN=1"
        append_log(entry)
        print(json.dumps({"success": True, "action": "dry_run", **entry}, indent=2))
        return 0

    if not safe_key:
        print("[rescue] FAIL: SAFE_PRIVATE_KEY required for live rescue", file=sys.stderr)
        return 1

    if remaining <= 0:
        entry["action"] = "blocked_daily_limit"
        entry["reason"] = f"daily limit {daily_limit} wei exhausted (spent {spent_24h})"
        append_log(entry)
        print(json.dumps({"success": False, **entry}, indent=2))
        return 1

    if rescue_wei > remaining:
        rescue_wei = remaining
        entry["rescue_wei"] = rescue_wei

    try:
        tx_hash = send_gas_cast(holder, rescue_wei, rpc_url, safe_key, chain_id)
        entry["action"] = "rescue_sent"
        entry["tx_hash"] = tx_hash
        append_log(entry)
        out = {"success": True, **entry}
        if pend > 0:
            out["next_step"] = "GAS_HOLDER funded — retry stuck pending tx from signing bot"
        print(json.dumps(out, indent=2))
        return 0
    except Exception as exc:
        entry["action"] = "error"
        entry["error"] = str(exc)
        append_log(entry)
        print(json.dumps({"success": False, **entry}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
