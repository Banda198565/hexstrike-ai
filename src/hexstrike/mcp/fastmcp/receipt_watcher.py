"""ReceiptWatcher — poll mined/fail and archive forensics logs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.core.execution.receipt_watcher import ReceiptWatcher as CoreWatcher

import hexstrike_tx as tx  # noqa: E402


class ReceiptWatcher:
    """Track transaction lifecycle after broadcast."""

    def __init__(self, log_dir: Path | None = None, timeout_sec: float = 120.0, poll_interval: float = 2.0) -> None:
        self.log_dir = log_dir or (ROOT / "tx_logs")
        self.timeout_sec = timeout_sec
        self.poll_interval = poll_interval
        self._core = CoreWatcher(rpc_call=tx.rpc_call, timeout_sec=timeout_sec, poll_interval_sec=poll_interval)

    def poll_status(self, tx_hash: str, rpc: str | None = None) -> dict[str, Any]:
        rpc = rpc or tx._rpc_url()
        return self._core.status_once(rpc, tx_hash)

    def watch(self, tx_hash: str, rpc: str | None = None) -> dict[str, Any]:
        rpc = rpc or tx._rpc_url()
        result = self._core.watch(rpc, tx_hash)
        self.log_receipt(result)
        return result

    def log_receipt(self, receipt_result: dict[str, Any], run_id: str | None = None) -> Path:
        rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        d = self.log_dir / rid
        d.mkdir(parents=True, exist_ok=True)
        log_path = d / "receipt.json"
        log_path.write_text(json.dumps(receipt_result, indent=2) + "\n", encoding="utf-8")
        latest = self.log_dir / "latest" / "receipt.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
        return log_path

    def retry_failed(self, tx_hash: str, *, max_attempts: int = 3) -> dict[str, Any]:
        """Re-poll a failed or timed-out hash (read-only recovery probe)."""
        rpc = tx._rpc_url()
        last: dict[str, Any] = {}
        for attempt in range(1, max_attempts + 1):
            last = self.poll_status(tx_hash, rpc)
            last["attempt"] = attempt
            if last.get("mined"):
                self.log_receipt(last)
                return last
        last["state"] = last.get("state", "pending")
        return last


class ReceiptWatcherMcp:
    """Static facade for MCP registration."""

    @staticmethod
    def watch(tx_hash: str, timeout_sec: float = 120.0) -> dict[str, Any]:
        return ReceiptWatcher(timeout_sec=timeout_sec).watch(tx_hash)
