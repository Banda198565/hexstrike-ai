#!/usr/bin/env python3
"""FastMCPCombat live cycle example — build → gate → sign → relay → watch → archive.

Usage (Mac operator):
  export VAULT_PASSPHRASE='your-passphrase'
  export BOT_PRIVATE_KEY='0x...'   # imported into vault on first run
  export HEXSTRIKE_TX_LIVE=1       # enable broadcast

  python3 scripts/run_fastmcp_combat_live.py --target 0xPAYROLL --value 0.001bnb

Dry-run (default without HEXSTRIKE_TX_LIVE):
  python3 scripts/run_fastmcp_combat_live.py --target 0x4943... --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv
from hexstrike.mcp.fastmcp import AllowlistManager, FastMCPCombat

load_dotenv(ROOT / ".env")


def main() -> int:
    p = argparse.ArgumentParser(description="FastMCPCombat live transaction cycle")
    p.add_argument("--target", required=True, help="Recipient address (0xPAYROLL)")
    p.add_argument("--value", default="0.001bnb")
    p.add_argument("--token", help="ERC20 contract address")
    p.add_argument("--amount", help="Token amount when --token set")
    p.add_argument("--allow-unknown", action="store_true", help="Bypass allowlist gate")
    p.add_argument("--dry-run", action="store_true", help="Force dry-run (no broadcast)")
    p.add_argument("--no-vault-bootstrap", action="store_true")
    p.add_argument("--add-recipient", help="Add address to allowlist before cycle")
    args = p.parse_args()

    combat = FastMCPCombat(auto_bootstrap_vault=not args.no_vault_bootstrap)

    if args.add_recipient:
        combat.allowlist.add_recipient(args.add_recipient)
    elif args.target and not args.allow_unknown:
        # Ensure target is allowlisted for demo payroll flow
        data = combat.allowlist.load()
        recipients = {a.lower() for a in data.get("authorized_recipients", [])}
        if args.target.lower() not in recipients:
            print(json.dumps({
                "warning": "target not in allowlist — gate will block sign",
                "hint": f"run with --add-recipient {args.target} or --allow-unknown",
            }, indent=2), file=sys.stderr)

    result = combat.execute_live_tx(
        target=args.target,
        value=args.value,
        token=args.token,
        amount=args.amount,
        allow_unknown=args.allow_unknown,
        dry_run=True if args.dry_run else None,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
