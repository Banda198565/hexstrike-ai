#!/usr/bin/env python3
"""HexStrike tx CLI — send / sign / broadcast / status (BSC/EVM, gated broadcast)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv
from crypto_rpc_orchestrator import load_config, rpc_call
from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.execution.broadcaster import ExecutionBroadcaster
from hexstrike.paths import PENDING_ACTION, RPC_CONFIG

load_dotenv(ROOT / ".env")


def _rpc_url() -> str:
    cfg = load_config(RPC_CONFIG)
    return os.environ.get("RPC_URL") or os.environ.get("DIRECT_RPC_URL") or cfg["primary"]


def _chain_id(rpc: str) -> int:
    env = os.environ.get("CHAIN_ID")
    if env:
        return int(env)
    return int(rpc_call(rpc, "eth_chainId", [])["result"], 16)


def _from_address() -> str:
    addr = os.environ.get("BOT_ADDRESS") or os.environ.get("FUNDER_ADDRESS") or ""
    if not addr:
        raise SystemExit("Set BOT_ADDRESS or FUNDER_ADDRESS in .env")
    return addr.lower() if addr.startswith("0x") else f"0x{addr.lower()}"


def _private_key() -> str:
    key = os.environ.get("BOT_PRIVATE_KEY", "").strip()
    if not key:
        raise SystemExit("BOT_PRIVATE_KEY not set — signing disabled (watch-only mode)")
    if not key.startswith("0x"):
        key = "0x" + key
    return key


def parse_value(raw: str) -> int:
    """Parse 0.001bnb / 0.001eth / 1000000000000000 / 0.001 (default native 18 dec)."""
    s = raw.strip().lower().replace("_", "")
    for suffix, dec in (("bnb", 18), ("eth", 18), ("wei", 0)):
        if s.endswith(suffix):
            num = s[: -len(suffix)].strip()
            return int(Decimal(num) * (Decimal(10) ** dec))
    if s.startswith("0x"):
        return int(s, 16)
    try:
        if "." in s:
            return int(Decimal(s) * Decimal(10**18))
        return int(s)
    except InvalidOperation as exc:
        raise SystemExit(f"Invalid --value: {raw}") from exc


def cmd_send(args: argparse.Namespace) -> int:
    rpc = _rpc_url()
    from_addr = _from_address()
    to_addr = args.target if args.target.startswith("0x") else f"0x{args.target}"
    value_wei = parse_value(args.value)
    chain_id = _chain_id(rpc)
    nonce = int(rpc_call(rpc, "eth_getTransactionCount", [from_addr, "pending"])["result"], 16)
    gas_price = int(rpc_call(rpc, "eth_gasPrice", [])["result"], 16)

    tx: dict[str, Any] = {
        "chainId": chain_id,
        "from": from_addr,
        "to": to_addr,
        "value": hex(value_wei),
        "nonce": nonce,
        "gas": hex(21000),
        "maxFeePerGas": hex(gas_price * 2),
        "maxPriorityFeePerGas": hex(gas_price),
        "type": 2,
    }

    bus = ContextBus()
    bc = ExecutionBroadcaster(bus=bus, config_path=RPC_CONFIG)
    pre = bc.preflight(tx)

    out = {
        "command": "send",
        "dry_run": args.dry_run,
        "rpc": rpc,
        "transaction": tx,
        "preflight": {
            "ok": pre.ok,
            "gas_estimate": pre.gas_estimate,
            "gas_price_wei": pre.gas_price_wei,
            "errors": pre.errors,
            "warnings": pre.warnings,
        },
    }

    if args.dry_run:
        out["result"] = "ok"
        out["note"] = "Dry-run — not signed or broadcast"
        print(json.dumps(out, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps(tx, indent=2) + "\n", encoding="utf-8")
        return 0

    queued = bc.queue_for_approval(tx, reason="hexstrike tx send")
    out["queued"] = queued
    out["pending_action"] = str(PENDING_ACTION)
    print(json.dumps(out, indent=2))
    return 0 if pre.ok else 1


def cmd_sign(args: argparse.Namespace) -> int:
    raw_path = Path(args.raw_tx)
    if not raw_path.is_file():
        raise SystemExit(f"Missing file: {raw_path}")

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tx = data.get("transaction", data)
    rpc = _rpc_url()

    if args.debug:
        dbg = {k: v for k, v in tx.items() if k not in ("privateKey",)}
        dbg["from_env"] = _from_address()
        print(json.dumps({"debug": dbg, "rpc": rpc}, indent=2), file=sys.stderr)

    try:
        from eth_account import Account  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit("pip install eth-account") from exc

    key = _private_key()
    acct = Account.from_key(key)

    # Normalize hex fields for eth_account
    norm: dict[str, Any] = {}
    for k, v in tx.items():
        if k in ("from", "privateKey"):
            continue
        if k in ("value", "gas", "maxFeePerGas", "maxPriorityFeePerGas", "gasPrice") and isinstance(v, str):
            norm[k] = int(v, 16) if v.startswith("0x") else int(v)
        elif k == "chainId" and isinstance(v, str) and v.startswith("0x"):
            norm[k] = int(v, 16)
        else:
            norm[k] = v

    if "chainId" not in norm:
        norm["chainId"] = _chain_id(rpc)
    if "nonce" not in norm:
        norm["nonce"] = int(
            rpc_call(rpc, "eth_getTransactionCount", [acct.address, "pending"])["result"], 16
        )

    signed = acct.sign_transaction(norm)
    raw_hex = signed.raw_transaction.hex()
    if not raw_hex.startswith("0x"):
        raw_hex = "0x" + raw_hex

    result = {
        "command": "sign",
        "from": acct.address,
        "raw": raw_hex,
        "hash": signed.hash.hex() if hasattr(signed, "hash") else None,
    }
    out_path = Path(args.out) if args.out else raw_path.with_name("signed_tx.json")
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "output": str(out_path)}, indent=2))
    return 0


def cmd_broadcast(args: argparse.Namespace) -> int:
    path = Path(args.signed_tx)
    if not path.is_file():
        raise SystemExit(f"Missing file: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_hex = data.get("raw") or data.get("signed_tx") or data.get("rawTransaction")
    if not raw_hex:
        raise SystemExit("signed_tx.json must contain 'raw' hex field")

    if args.force:
        if PENDING_ACTION.is_file():
            pending = json.loads(PENDING_ACTION.read_text(encoding="utf-8"))
        else:
            pending = {"status": "awaiting_operator_review", "action": "broadcast_tx"}
        pending["status"] = "approved"
        pending["approved_by"] = "hexstrike tx broadcast --force"
        PENDING_ACTION.parent.mkdir(parents=True, exist_ok=True)
        PENDING_ACTION.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")

    bus = ContextBus()
    bc = ExecutionBroadcaster(bus=bus, config_path=RPC_CONFIG)
    result = bc.broadcast(raw_hex, approved=args.force)
    print(json.dumps({"command": "broadcast", **result}, indent=2))
    return 0 if result.get("success") else 1


def cmd_status(args: argparse.Namespace) -> int:
    rpc = _rpc_url()
    tx_hash = args.hash if args.hash.startswith("0x") else f"0x{args.hash}"
    tx = rpc_call(rpc, "eth_getTransactionByHash", [tx_hash])
    receipt = rpc_call(rpc, "eth_getTransactionReceipt", [tx_hash])
    out = {
        "command": "status",
        "hash": tx_hash,
        "rpc": rpc,
        "transaction": tx.get("result"),
        "receipt": receipt.get("result"),
        "mined": receipt.get("result") is not None,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        r = out["receipt"]
        if r:
            print(f"mined block={int(r.get('blockNumber','0x0'),16)} status={int(r.get('status','0x0'),16)}")
        else:
            print("pending or not found")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hexstrike tx", description="HexStrike transaction CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    send_p = sub.add_parser("send", help="Build tx + preflight (default dry-run)")
    send_p.add_argument("target", help="0x recipient")
    send_p.add_argument("--value", required=True, help="e.g. 0.001bnb")
    send_p.add_argument("--dry-run", action="store_true", default=False, help="Preflight only")
    send_p.add_argument("--out", help="Write unsigned tx JSON")
    send_p.set_defaults(func=cmd_send)

    sign_p = sub.add_parser("sign", help="Sign unsigned tx JSON")
    sign_p.add_argument("raw_tx", help="raw_tx.json path")
    sign_p.add_argument("--debug", action="store_true")
    sign_p.add_argument("--out", help="Output signed_tx.json path")
    sign_p.set_defaults(func=cmd_sign)

    bc_p = sub.add_parser("broadcast", help="Broadcast signed raw tx (approval gate)")
    bc_p.add_argument("signed_tx", help="signed_tx.json path")
    bc_p.add_argument("--force", action="store_true", help="Auto-approve pending_action for this broadcast")
    bc_p.set_defaults(func=cmd_broadcast)

    st_p = sub.add_parser("status", help="Tx / receipt status")
    st_p.add_argument("hash", help="0x transaction hash")
    st_p.add_argument("--json", action="store_true")
    st_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    # Default send to dry-run unless LIVE=1
    if args.cmd == "send" and not os.environ.get("HEXSTRIKE_TX_LIVE", "").lower() in ("1", "true", "yes"):
        if not getattr(args, "dry_run", False) and "--dry-run" not in sys.argv:
            args.dry_run = True
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
