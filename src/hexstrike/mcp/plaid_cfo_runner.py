"""Read-only Plaid API client for Personal CFO workflows.

Credentials in MCP env only: PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKEN.
Optional: PLAID_ENV=sandbox|production (default sandbox).

Non-emulation: real API responses only; skipped when credentials missing.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

_PLAID_BASE = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}

_ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "plaid-cfo"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _audit_id(prefix: str = "plaid") -> str:
    return f"{prefix}-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"


def _save_report(audit_id: str, payload: dict[str, Any], suffix: str) -> str:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = _ARTIFACTS / f"{audit_id}-{suffix}.json"
    import json

    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return str(path)


def _plaid_config() -> dict[str, Any]:
    client_id = os.environ.get("PLAID_CLIENT_ID", "").strip()
    secret = os.environ.get("PLAID_SECRET", "").strip()
    access_token = os.environ.get("PLAID_ACCESS_TOKEN", "").strip()
    env = os.environ.get("PLAID_ENV", "sandbox").strip().lower()
    if env not in _PLAID_BASE:
        env = "sandbox"
    return {
        "client_id_set": bool(client_id),
        "secret_set": bool(secret),
        "access_token_set": bool(access_token),
        "env": env,
        "base_url": _PLAID_BASE[env],
        "client_id": client_id,
        "secret": secret,
        "access_token": access_token,
    }


def detect_plaid_config() -> dict[str, Any]:
    """Report Plaid credential availability (no secrets in output)."""
    cfg = _plaid_config()
    ready = cfg["client_id_set"] and cfg["secret_set"] and cfg["access_token_set"]
    return {
        "success": True,
        "ready": ready,
        "env": cfg["env"],
        "base_url": cfg["base_url"],
        "client_id_set": cfg["client_id_set"],
        "secret_set": cfg["secret_set"],
        "access_token_set": cfg["access_token_set"],
        "read_only": True,
        "skipped": not ready,
        "reason": None if ready else "Set PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKEN in MCP env",
    }


def _skipped(reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "skipped": True,
        "reason": reason,
        "read_only": True,
    }


def _plaid_post(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    cfg = _plaid_config()
    if not (cfg["client_id_set"] and cfg["secret_set"]):
        return _skipped("PLAID_CLIENT_ID and PLAID_SECRET required")
    if "access_token" in body and not cfg["access_token_set"]:
        return _skipped("PLAID_ACCESS_TOKEN required")

    payload = {
        "client_id": cfg["client_id"],
        "secret": cfg["secret"],
        **body,
    }
    url = f"{cfg['base_url']}{endpoint}"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return {
                "success": False,
                "error": data.get("error_message") or data.get("error") or resp.text[:500],
                "error_code": data.get("error_code"),
                "read_only": True,
            }
        return {"success": True, "data": data, "read_only": True}
    except requests.RequestException as exc:
        return {"success": False, "error": str(exc), "read_only": True}


def plaid_accounts_list() -> dict[str, Any]:
    """List linked accounts (balances, types) — read-only."""
    audit_id = _audit_id()
    result = _plaid_post("/accounts/balance/get", {"access_token": _plaid_config()["access_token"]})
    if not result.get("success"):
        return {**result, "audit_id": audit_id}

    accounts = result.get("data", {}).get("accounts") or []
    summary = []
    for acc in accounts:
        bal = acc.get("balances") or {}
        summary.append(
            {
                "account_id": acc.get("account_id"),
                "name": acc.get("name"),
                "type": acc.get("type"),
                "subtype": acc.get("subtype"),
                "mask": acc.get("mask"),
                "current": bal.get("current"),
                "available": bal.get("available"),
                "iso_currency": bal.get("iso_currency_code"),
            }
        )
    out = {
        "success": True,
        "audit_id": audit_id,
        "source": "plaid",
        "account_count": len(summary),
        "accounts": summary,
        "read_only": True,
    }
    out["raw_report_path"] = _save_report(audit_id, out, "accounts")
    return out


def plaid_transactions_list(
    days: int = 30,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Recent transactions across linked accounts — read-only."""
    audit_id = _audit_id()
    cfg = _plaid_config()
    if not cfg["access_token_set"]:
        return {**_skipped("PLAID_ACCESS_TOKEN required"), "audit_id": audit_id}

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, min(days, 730)))
    body: dict[str, Any] = {
        "access_token": cfg["access_token"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "options": {"count": 100, "offset": 0},
    }
    if account_id:
        body["options"]["account_ids"] = [account_id]

    result = _plaid_post("/transactions/get", body)
    if not result.get("success"):
        return {**result, "audit_id": audit_id}

    txs = result.get("data", {}).get("transactions") or []
    rows = []
    for tx in txs[:100]:
        rows.append(
            {
                "date": tx.get("date"),
                "name": tx.get("name"),
                "amount": tx.get("amount"),
                "category": tx.get("category"),
                "account_id": tx.get("account_id"),
                "pending": tx.get("pending"),
            }
        )
    out = {
        "success": True,
        "audit_id": audit_id,
        "source": "plaid",
        "period_days": days,
        "transaction_count": len(rows),
        "transactions": rows,
        "read_only": True,
    }
    out["raw_report_path"] = _save_report(audit_id, out, "transactions")
    return out


def plaid_investments_holdings() -> dict[str, Any]:
    """Investment holdings and securities — read-only."""
    audit_id = _audit_id()
    result = _plaid_post("/investments/holdings/get", {"access_token": _plaid_config()["access_token"]})
    if not result.get("success"):
        return {**result, "audit_id": audit_id}

    data = result.get("data") or {}
    holdings = data.get("holdings") or []
    securities = {s.get("security_id"): s for s in (data.get("securities") or [])}
    rows = []
    for h in holdings:
        sec = securities.get(h.get("security_id")) or {}
        rows.append(
            {
                "account_id": h.get("account_id"),
                "quantity": h.get("quantity"),
                "inst_value": h.get("institution_value"),
                "cost_basis": h.get("cost_basis"),
                "ticker": sec.get("ticker_symbol"),
                "name": sec.get("name"),
                "type": sec.get("type"),
            }
        )
    out = {
        "success": True,
        "audit_id": audit_id,
        "source": "plaid",
        "holding_count": len(rows),
        "holdings": rows,
        "read_only": True,
    }
    out["raw_report_path"] = _save_report(audit_id, out, "holdings")
    return out


def plaid_liabilities_list() -> dict[str, Any]:
    """Loans, credit cards, mortgages — read-only."""
    audit_id = _audit_id()
    result = _plaid_post("/liabilities/get", {"access_token": _plaid_config()["access_token"]})
    if not result.get("success"):
        return {**result, "audit_id": audit_id}

    data = result.get("data") or {}
    liab = data.get("liabilities") or {}
    out = {
        "success": True,
        "audit_id": audit_id,
        "source": "plaid",
        "credit_count": len(liab.get("credit") or []),
        "mortgage_count": len(liab.get("mortgage") or []),
        "student_count": len(liab.get("student") or []),
        "liabilities": liab,
        "read_only": True,
    }
    out["raw_report_path"] = _save_report(audit_id, out, "liabilities")
    return out


def plaid_cfo_summary(days: int = 30) -> dict[str, Any]:
    """Composite Personal CFO snapshot — accounts, recent txs, holdings, liabilities."""
    audit_id = _audit_id()
    detect = detect_plaid_config()
    if detect.get("skipped"):
        return {**detect, "audit_id": audit_id}

    accounts = plaid_accounts_list()
    transactions = plaid_transactions_list(days=days)
    holdings = plaid_investments_holdings()
    liabilities = plaid_liabilities_list()

    total_current = sum(
        (a.get("current") or 0) for a in (accounts.get("accounts") or []) if isinstance(a.get("current"), (int, float))
    )

    out = {
        "success": True,
        "audit_id": audit_id,
        "source": "plaid_cfo",
        "summary": {
            "account_count": accounts.get("account_count", 0),
            "total_current_balance": total_current,
            "recent_transaction_count": transactions.get("transaction_count", 0),
            "holding_count": holdings.get("holding_count", 0),
            "liability_buckets": {
                "credit": liabilities.get("credit_count", 0),
                "mortgage": liabilities.get("mortgage_count", 0),
                "student": liabilities.get("student_count", 0),
            },
        },
        "accounts": accounts if accounts.get("success") else {"skipped": True, "reason": accounts.get("reason")},
        "transactions": transactions if transactions.get("success") else {"skipped": True},
        "holdings": holdings if holdings.get("success") else {"skipped": True},
        "liabilities": liabilities if liabilities.get("success") else {"skipped": True},
        "read_only": True,
    }
    out["raw_report_path"] = _save_report(audit_id, out, "cfo-summary")
    return out
