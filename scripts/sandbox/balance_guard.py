"""Defensive balance validation for sandbox dummy bot (Step 3 — hardening)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALERTS = ROOT / "artifacts" / "sandbox" / "anomaly-alerts.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_alert(entry: dict[str, Any]) -> None:
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def rpc_call(url: str, method: str, params: list[Any], timeout: float = 10.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def fetch_balance(url: str, address: str) -> int:
    result = rpc_call(url, "eth_getBalance", [address, "latest"])
    return int(result, 16)


def fetch_nonce(url: str, address: str) -> int:
    result = rpc_call(url, "eth_getTransactionCount", [address, "latest"])
    return int(result, 16)


@dataclass(frozen=True)
class GuardConfig:
    primary_rpc: str
    direct_rpc: str
    address: str
    enabled: bool

    @classmethod
    def from_env(cls) -> GuardConfig:
        primary = os.environ.get("RPC_URL", "http://127.0.0.1:8546")
        direct = os.environ.get("DIRECT_RPC_URL", os.environ.get("UPSTREAM_RPC", "http://127.0.0.1:8545"))
        enabled = os.environ.get("HARDENING_ENABLED", "").lower() in ("1", "true", "yes")
        return cls(
            primary_rpc=primary,
            direct_rpc=direct,
            address=os.environ["BOT_ADDRESS"],
            enabled=enabled,
        )


@dataclass
class GuardState:
    last_balance: int | None = None
    last_nonce: int | None = None


@dataclass(frozen=True)
class BalanceSnapshot:
    primary_wei: int
    direct_wei: int
    match: bool
    delta_wei: int


def multi_source_balance(cfg: GuardConfig) -> BalanceSnapshot:
    primary = fetch_balance(cfg.primary_rpc, cfg.address)
    direct = fetch_balance(cfg.direct_rpc, cfg.address)
    return BalanceSnapshot(
        primary_wei=primary,
        direct_wei=direct,
        match=primary == direct,
        delta_wei=abs(primary - direct),
    )


def detect_rpc_mismatch(snapshot: BalanceSnapshot) -> dict[str, Any] | None:
    if snapshot.match:
        return None
    alert = {
        "ts": utc_now(),
        "type": "rpc_mismatch",
        "severity": "critical",
        "primary_wei": snapshot.primary_wei,
        "direct_wei": snapshot.direct_wei,
        "delta_wei": snapshot.delta_wei,
        "action": "block_signing",
        "message": "Primary RPC balance differs from direct upstream — possible tampering",
    }
    append_alert(alert)
    return alert


def detect_anomaly_no_onchain_activity(
    cfg: GuardConfig,
    state: GuardState,
    current_balance: int,
) -> dict[str, Any] | None:
    """Flag balance drop without a matching nonce increase on direct RPC."""
    if state.last_balance is None or state.last_nonce is None:
        return None
    if current_balance >= state.last_balance:
        return None

    current_nonce = fetch_nonce(cfg.direct_rpc, cfg.address)
    if current_nonce > state.last_nonce:
        return None

    alert = {
        "ts": utc_now(),
        "type": "anomaly_no_onchain_activity",
        "severity": "high",
        "prev_balance_wei": state.last_balance,
        "current_balance_wei": current_balance,
        "nonce": current_nonce,
        "prev_nonce": state.last_nonce,
        "action": "block_signing",
        "message": "Balance dropped but no new tx from wallet on direct RPC",
    }
    append_alert(alert)
    return alert


def pre_sign_verify(cfg: GuardConfig, threshold_wei: int) -> tuple[bool, dict[str, Any]]:
    """Allow signing only when direct RPC also confirms balance below threshold."""
    direct_bal = fetch_balance(cfg.direct_rpc, cfg.address)
    ok = direct_bal < threshold_wei
    detail: dict[str, Any] = {
        "ts": utc_now(),
        "type": "pre_sign_verify",
        "direct_wei": direct_bal,
        "threshold_wei": threshold_wei,
        "allowed": ok,
    }
    if not ok:
        detail["severity"] = "critical"
        detail["action"] = "block_signing"
        detail["message"] = "Direct RPC balance above threshold — proxy trigger rejected"
        append_alert(detail)
    return ok, detail


def evaluate_poll(cfg: GuardConfig, state: GuardState) -> dict[str, Any]:
    """Run all defensive checks; return decision payload for bot event log."""
    snapshot = multi_source_balance(cfg)
    checks: dict[str, Any] = {
        "hardening": True,
        "primary_wei": snapshot.primary_wei,
        "direct_wei": snapshot.direct_wei,
        "balances_match": snapshot.match,
        "use_balance_wei": snapshot.direct_wei,
        "block_signing": False,
        "block_reason": None,
        "alerts": [],
    }

    mismatch = detect_rpc_mismatch(snapshot)
    if mismatch:
        checks["block_signing"] = True
        checks["block_reason"] = "rpc_mismatch"
        checks["alerts"].append(mismatch)
        checks["use_balance_wei"] = snapshot.direct_wei

    anomaly = detect_anomaly_no_onchain_activity(cfg, state, snapshot.direct_wei)
    if anomaly:
        checks["block_signing"] = True
        checks["block_reason"] = checks["block_reason"] or "anomaly_no_onchain_activity"
        checks["alerts"].append(anomaly)

    state.last_balance = snapshot.direct_wei
    state.last_nonce = fetch_nonce(cfg.direct_rpc, cfg.address)
    return checks
