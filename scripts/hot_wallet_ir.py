"""Hot wallet mempool IR: threat classification for pending outflows (defensive only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWLIST = ROOT / "config" / "hot-wallet-allowlist.json"

ERC20_TRANSFER = "a9059cbb"
IR_TRIGGER_SCORE = 70


def _ir_trigger_score() -> int:
    import os
    return int(os.environ.get("HOT_WALLET_IR_SCORE", "70"))


def normalize_addr(addr: str | None) -> str:
    if not addr:
        return ""
    a = addr.strip().lower()
    return a if a.startswith("0x") else f"0x{a}"


def load_allowlist(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_ALLOWLIST
    if not p.is_file():
        return {"authorized_recipients": [], "authorized_contracts": []}
    return json.loads(p.read_text(encoding="utf-8"))


def decode_erc20_transfer(input_hex: str) -> tuple[str | None, int | None]:
    """Return (recipient, amount) for transfer(address,uint256) or (None, None)."""
    raw = (input_hex or "0x").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) < 8 + 64 + 64:
        return None, None
    if raw[:8] != ERC20_TRANSFER:
        return None, None
    recipient = "0x" + raw[8 + 24 : 8 + 64]
    try:
        amount = int(raw[8 + 64 : 8 + 128], 16)
    except ValueError:
        amount = None
    return normalize_addr(recipient), amount


def _tx_native_value_wei(tx: dict[str, Any]) -> int:
    raw = tx.get("value") or "0x0"
    if isinstance(raw, int):
        return max(raw, 0)
    if isinstance(raw, str):
        try:
            return int(raw, 16)
        except ValueError:
            return 0
    return 0


def classify_hot_wallet_outflow(
    tx: dict[str, Any],
    hot_wallet: str,
    allowlist: dict[str, Any] | None = None,
    sinks: set[str] | None = None,
) -> dict[str, Any]:
    """Score pending hot-wallet outflow: higher = more urgent IR."""
    allowlist = allowlist or load_allowlist()
    sinks = sinks or set()
    hw = normalize_addr(hot_wallet)
    to = normalize_addr(tx.get("to"))
    reasons: list[str] = []
    score = 40  # baseline: any outflow from hot wallet

    auth_recipients = {normalize_addr(a) for a in allowlist.get("authorized_recipients", [])}
    auth_contracts = {normalize_addr(a) for a in allowlist.get("authorized_contracts", [])}

    erc20_to, erc20_amt = decode_erc20_transfer(tx.get("input") or "0x")
    effective_to = erc20_to or to

    if effective_to in auth_recipients:
        score = 15
        reasons.append("authorized_payroll_recipient")
    elif to in auth_contracts and erc20_to and erc20_to in auth_recipients:
        score = 25
        reasons.append("authorized_token_contract_transfer")
    elif to in auth_contracts and erc20_to:
        score = 80
        reasons.append("unknown_recipient_via_authorized_token")
    elif effective_to in auth_contracts:
        score = 30
        reasons.append("authorized_contract_interaction")
    else:
        reasons.append("unknown_recipient")
        score = 75

    if effective_to in sinks:
        score = min(100, score + 25)
        reasons.append("known_sink_interaction")

    native = _tx_native_value_wei(tx)
    if native > 10**17:  # > 0.1 BNB native
        score = min(100, score + 15)
        reasons.append("high_native_value")

    if erc20_amt is not None and erc20_amt >= 10**20:  # heuristic large token amount
        score = min(100, score + 10)
        reasons.append("large_erc20_transfer")

    if score >= 85:
        level = "CRITICAL"
    elif score >= 50:
        level = "WARN"
    else:
        level = "INFO"

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_reasons": reasons,
        "ir_trigger": score >= _ir_trigger_score(),
        "effective_to": effective_to,
        "erc20_recipient": erc20_to,
        "erc20_amount": erc20_amt,
        "native_value_wei": native,
    }
