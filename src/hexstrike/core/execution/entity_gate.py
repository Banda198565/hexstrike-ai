"""Allowlist / entity gate before transaction signing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from hot_wallet_ir import classify_hot_wallet_outflow, decode_erc20_transfer, load_allowlist, normalize_addr  # noqa: E402


def _tx_value_wei(tx: dict[str, Any]) -> int:
    v = tx.get("value", "0x0")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 16) if v.startswith("0x") else int(v)
    return 0


def gate_transaction(tx: dict[str, Any], *, from_addr: str, allowlist_path: Path | None = None) -> dict[str, Any]:
    """Return {allowed, reasons, classification} — blocks unknown high-risk recipients."""
    allowlist = load_allowlist(allowlist_path)
    hot = normalize_addr(allowlist.get("hot_wallet") or from_addr)
    classification = classify_hot_wallet_outflow(tx, hot, allowlist=allowlist)

    erc20_to, _ = decode_erc20_transfer(tx.get("data") or tx.get("input") or "0x")
    to_addr = normalize_addr(tx.get("to"))
    effective = erc20_to or to_addr

    auth_recipients = {normalize_addr(a) for a in allowlist.get("authorized_recipients", [])}
    auth_contracts = {normalize_addr(a) for a in allowlist.get("authorized_contracts", [])}

    allowed = True
    reasons: list[str] = []

    if effective in auth_recipients:
        reasons.append("allowlist_recipient")
    elif to_addr in auth_contracts and erc20_to and erc20_to in auth_recipients:
        reasons.append("allowlist_token_rail")
    elif to_addr in auth_contracts and erc20_to:
        allowed = False
        reasons.append("blocked_unknown_erc20_recipient")
    elif effective in auth_contracts:
        reasons.append("allowlist_contract")
    elif _tx_value_wei(tx) == 0 and not erc20_to:
        reasons.append("empty_call_allowed_for_review")
    else:
        # Unknown recipient — require explicit override
        import os
        if os.environ.get("HEXSTRIKE_TX_ALLOW_UNKNOWN", "").lower() not in ("1", "true", "yes"):
            allowed = False
            reasons.append("blocked_unknown_recipient")
        else:
            reasons.append("override_HEXSTRIKE_TX_ALLOW_UNKNOWN")

    if classification.get("ir_trigger"):
        reasons.append("ir_trigger_classification")

    return {
        "allowed": allowed,
        "reasons": reasons,
        "classification": classification,
        "effective_to": effective,
    }
