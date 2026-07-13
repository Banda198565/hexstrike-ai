"""Poll eth_getTransactionReceipt until mined or timeout."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class ReceiptWatcher:
    """Watch transaction until success, fail, or timeout."""

    rpc_call: Callable[..., dict[str, Any]]
    poll_interval_sec: float = 2.0
    timeout_sec: float = 120.0

    def status_once(self, rpc: str, tx_hash: str) -> dict[str, Any]:
        h = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
        receipt = self.rpc_call(rpc, "eth_getTransactionReceipt", [h]).get("result")
        tx = self.rpc_call(rpc, "eth_getTransactionByHash", [h]).get("result")
        state = "pending"
        if receipt:
            state = "success" if int(receipt.get("status", "0x0"), 16) == 1 else "fail"
        return {
            "hash": h,
            "state": state,
            "mined": receipt is not None,
            "transaction": tx,
            "receipt": receipt,
        }

    def watch(self, rpc: str, tx_hash: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_sec
        polls = 0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.status_once(rpc, tx_hash)
            polls += 1
            if last.get("mined"):
                last["polls"] = polls
                last["finished_at"] = datetime.now(timezone.utc).isoformat()
                last["success"] = last.get("state") == "success"
                return last
            time.sleep(self.poll_interval_sec)
        last["polls"] = polls
        last["state"] = "timeout"
        last["success"] = False
        last["finished_at"] = datetime.now(timezone.utc).isoformat()
        return last
