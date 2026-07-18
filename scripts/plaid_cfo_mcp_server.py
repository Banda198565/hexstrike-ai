#!/usr/bin/env python3
"""HexStrike Personal CFO / Plaid MCP Server — read-only financial analytics.

Env (MCP server only — never in agent prompts):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKEN
  PLAID_ENV=sandbox|production

Usage:
  python3 scripts/plaid_cfo_mcp_server.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.fastmcp import FastMCP

from hexstrike.mcp import plaid_cfo_runner as pcr

mcp = FastMCP("plaid_cfo_mcp")


@mcp.tool()
def detect_plaid_config() -> str:
    """Check Plaid credentials in MCP env (no secrets exposed)."""
    return json.dumps(pcr.detect_plaid_config(), ensure_ascii=False)


@mcp.tool()
def plaid_accounts_list() -> str:
    """List linked account balances and types (read-only)."""
    return json.dumps(pcr.plaid_accounts_list(), ensure_ascii=False)


@mcp.tool()
def plaid_transactions_list(days: int = 30, account_id: Optional[str] = None) -> str:
    """Recent transactions from linked accounts (read-only)."""
    return json.dumps(pcr.plaid_transactions_list(days=days, account_id=account_id), ensure_ascii=False)


@mcp.tool()
def plaid_investments_holdings() -> str:
    """Investment holdings and securities (read-only)."""
    return json.dumps(pcr.plaid_investments_holdings(), ensure_ascii=False)


@mcp.tool()
def plaid_liabilities_list() -> str:
    """Loans, credit cards, mortgages (read-only)."""
    return json.dumps(pcr.plaid_liabilities_list(), ensure_ascii=False)


@mcp.tool()
def plaid_cfo_summary(days: int = 30) -> str:
    """Personal CFO one-shot: accounts + transactions + holdings + liabilities."""
    return json.dumps(pcr.plaid_cfo_summary(days=days), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
