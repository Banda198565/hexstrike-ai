#!/usr/bin/env python3
"""HexStrike tx CLI — send / sign / broadcast / status / rescue (BSC/EVM, gated broadcast)."""
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
from hexstrike.core.vault.keyvault_signer import KeyVaultSigner
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


def _addr_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Set {name} in .env")
    return v if v.startswith("0x") else f"0x{v}"


def _private_key(env_name: str = "BOT_PRIVATE_KEY") -> str:
    key = os.environ.get(env_name, "").strip()
    if not key and env_name == "BOT_PRIVATE_KEY":
        key = os.environ.get("SAFE_PRIVATE_KEY", "").strip()
    if not key:
        raise SystemExit(f"{env_name} not set — signing disabled (watch-only mode)")
    return key if key.startswith("0x") else f"0x{key}"


def parse_value(raw: str) -> int:
    s = raw.strip().lower().replace("_", "")
    for suffix, dec in (("bnb", 18), ("eth", 18), ("wei", 0)):
        if s.endswith(suffix):
            return int(Decimal(s[: -len(suffix)].strip()) * (Decimal(10) ** dec))
    if s.startswith("0x"):
        return int(s, 16)
    try:
        return int(Decimal(s) * Decimal(10**18)) if "." in s else int(s)
    except InvalidOperation as exc:
        raise SystemExit(f"Invalid --value: {raw}") from exc


def _build_tx(*, from_addr: str, to_addr: str, value_wei: int, gas: int, rpc: str) -> dict[str, Any]:
    gas_price = int(rpc_call(rpc, "eth_gasPrice", [])["result"], 16)
    return {
        "chainId": _chain_id(rpc),
        "from": from_addr,
        "to": to_addr,
        "value": hex(value_wei),
        "nonce": int(rpc_call(rpc, "eth_getTransactionCount", [from_addr, "pending"])["result"], 16),
        "gas": hex(gas),
        "maxFeePerGas": hex(gas_price * 2),
        "maxPriorityFeePerGas": hex(gas_price),
        "type": 2,
    }


def _live_enabled() -> bool:
    return os.environ.get("HEXSTRIKE_TX_LIVE", "").lower() in ("1", "true", "yes")


def _resolve_signer_module(module: str, *, vault_key: str | None = None) -> tuple[str, str]:
    """Return (module_name, private_key_hex)."""
    mod = module or os.environ.get("TX_SIGN_MODULE", "EnvSigner")
    if mod == "KeyVaultSigner":
        signer = KeyVaultSigner(key_name=vault_key)
        return mod, signer.private_key_hex()
    if mod == "SafeSigner":
        return mod, _private_key("SAFE_PRIVATE_KEY")
    if mod in ("EnvSigner", "DefaultSigner", ""):
        return "EnvSigner", _private_key("BOT_PRIVATE_KEY")
    raise SystemExit(f"Unknown sign module: {mod} (use EnvSigner, KeyVaultSigner, SafeSigner)")


def _sign_tx_dict(tx: dict[str, Any], *, private_key: str, rpc: str) -> dict[str, Any]:
    try:
        from eth_account import Account  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit("pip install eth-account") from exc

    key = private_key if private_key.startswith("0x") else f"0x{private_key}"
    acct = Account.from_key(key)
    norm: dict[str, Any] = {}
    for k, v in tx.items():
        if k in ("from", "privateKey"):
            continue
        if k in ("value", "gas", "maxFeePerGas", "maxPriorityFeePerGas", "gasPrice") and isinstance(v, str):
            norm[k] = int(v, 16) if str(v).startswith("0x") else int(v)
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
    return {
        "from": acct.address,
        "raw": raw_hex,
        "hash": signed.hash.hex() if hasattr(signed, "hash") else None,
        "signer_module": None,
    }


def _cmd_build_or_send(args: argparse.Namespace, *, command: str) -> int:
    rpc = _rpc_url()
    target = getattr(args, "target", None)
    if not target:
        raise SystemExit("--target required")
    to_addr = target if target.startswith("0x") else f"0x{target}"
    tx = _build_tx(
        from_addr=_from_address(),
        to_addr=to_addr,
        value_wei=parse_value(args.value),
        gas=int(args.gas),
        rpc=rpc,
    )
    data = getattr(args, "data", None)
    if data and data != "0x":
        tx["data"] = data if data.startswith("0x") else f"0x{data}"
    pre = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).preflight(tx)
    out_path = Path(args.out) if args.out else ROOT / "artifacts" / "tx" / "raw_tx.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out: dict[str, Any] = {
        "command": command,
        "dry_run": args.dry_run,
        "rpc": rpc,
        "transaction": tx,
        "raw_tx_path": str(out_path),
        "preflight": {
            "ok": pre.ok,
            "gas_estimate": pre.gas_estimate,
            "gas_price_wei": pre.gas_price_wei,
            "errors": pre.errors,
            "warnings": pre.warnings,
        },
    }
    if args.dry_run or command == "build":
        out_path.write_text(json.dumps({"transaction": tx}, indent=2) + "\n", encoding="utf-8")
        out["result"] = "ok"
        out["note"] = "Dry-run — not signed or broadcast" if args.dry_run else "Built — sign with hexstrike tx sign"
        print(json.dumps(out, indent=2))
        return 0 if pre.ok else 1

    bc = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG)
    out["queued"] = bc.queue_for_approval(tx, reason=f"hexstrike tx {command}")
    out["pending_action"] = str(PENDING_ACTION)
    print(json.dumps(out, indent=2))
    return 0 if pre.ok else 1


def cmd_build(args: argparse.Namespace) -> int:
    args.dry_run = True
    return _cmd_build_or_send(args, command="build")


def cmd_send(args: argparse.Namespace) -> int:
    return _cmd_build_or_send(args, command="send")


def cmd_sign(args: argparse.Namespace) -> int:
    raw_path = Path(args.raw_tx)
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tx = data.get("transaction", data)
    rpc = _rpc_url()
    module = getattr(args, "module", None) or "EnvSigner"
    vault_key = getattr(args, "vault_key", None)
    if args.debug:
        print(json.dumps({"debug": {k: v for k, v in tx.items() if k != "privateKey"}, "rpc": rpc, "module": module}, indent=2), file=sys.stderr)
    mod_name, pk = _resolve_signer_module(module, vault_key=vault_key)
    signed = _sign_tx_dict(tx, private_key=pk, rpc=rpc)
    signed["signer_module"] = mod_name
    result = {"command": "sign", **signed}
    out_path = Path(args.out) if args.out else raw_path.with_name("signed_tx.json")
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "output": str(out_path)}, indent=2))
    return 0


def cmd_broadcast(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.signed_tx).read_text(encoding="utf-8"))
    raw_hex = data.get("raw") or data.get("signed_tx") or data.get("rawTransaction")
    if not raw_hex:
        raise SystemExit("signed_tx.json must contain 'raw' hex field")
    approved = args.force or _live_enabled()
    if approved:
        pending = json.loads(PENDING_ACTION.read_text(encoding="utf-8")) if PENDING_ACTION.is_file() else {}
        pending.update({
            "status": "approved",
            "approved_by": "hexstrike tx broadcast" + (" --force" if args.force else " (HEXSTRIKE_TX_LIVE)"),
            "action": "broadcast_tx",
        })
        PENDING_ACTION.parent.mkdir(parents=True, exist_ok=True)
        PENDING_ACTION.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
    result = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).broadcast(raw_hex, approved=approved)
    print(json.dumps({"command": "broadcast", **result}, indent=2))
    return 0 if result.get("success") else 1


def cmd_status(args: argparse.Namespace) -> int:
    rpc = _rpc_url()
    tx_hash = args.hash if args.hash.startswith("0x") else f"0x{args.hash}"
    receipt = rpc_call(rpc, "eth_getTransactionReceipt", [tx_hash]).get("result")
    tx = rpc_call(rpc, "eth_getTransactionByHash", [tx_hash]).get("result")
    state = "pending"
    if receipt:
        state = "success" if int(receipt.get("status", "0x0"), 16) == 1 else "fail"
    out = {"command": "status", "hash": tx_hash, "state": state, "rpc": rpc, "transaction": tx, "receipt": receipt, "mined": receipt is not None}
    print(json.dumps(out, indent=2) if args.json else json.dumps(out, indent=2))
    return 0


def cmd_rescue(args: argparse.Namespace) -> int:
    """SAFE → GAS_HOLDER native top-up (gas rescue)."""
    rpc = _rpc_url()
    safe = _addr_env("SAFE_ADDRESS")
    target = args.target or os.environ.get("GAS_HOLDER_ADDRESS", "")
    if not target:
        raise SystemExit("Set GAS_HOLDER_ADDRESS or --target")
    to_addr = target if target.startswith("0x") else f"0x{target}"
    gas = int(args.gas)
    value_wei = parse_value(args.value)
    tx = _build_tx(from_addr=safe, to_addr=to_addr, value_wei=value_wei, gas=gas, rpc=rpc)
    out_path = ROOT / "artifacts" / "tx" / "rescue_raw_tx.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out: dict[str, Any] = {
        "command": "rescue",
        "dry_run": args.dry_run,
        "from_safe": safe,
        "to_gas_holder": to_addr,
        "transaction": tx,
        "raw_tx_path": str(out_path),
    }
    if args.dry_run:
        out_path.write_text(json.dumps({"transaction": tx}, indent=2) + "\n", encoding="utf-8")
        out["result"] = "ok"
        out["note"] = "Rescue dry-run — SAFE top-up not broadcast"
        print(json.dumps(out, indent=2))
        return 0

    signed = _sign_tx_dict(tx, private_key=_private_key("SAFE_PRIVATE_KEY"), rpc=rpc)
    signed["signer_module"] = "SafeSigner"
    signed_path = ROOT / "artifacts" / "tx" / "rescue_signed_tx.json"
    signed_path.write_text(json.dumps({"command": "rescue_sign", **signed}, indent=2) + "\n", encoding="utf-8")
    if PENDING_ACTION.is_file():
        pending = json.loads(PENDING_ACTION.read_text(encoding="utf-8"))
    else:
        pending = {}
    pending.update({"status": "approved", "approved_by": "hexstrike tx rescue", "action": "broadcast_tx"})
    PENDING_ACTION.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
    result = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).broadcast(signed["raw"], approved=True)
    out["signed_path"] = str(signed_path)
    out["broadcast"] = result
    print(json.dumps(out, indent=2))
    return 0 if result.get("success") else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="hexstrike tx")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build_p = sub.add_parser("build", help="Build raw tx payload (always saves raw_tx.json)")
    build_p.add_argument("--target", required=True)
    build_p.add_argument("--value", required=True)
    build_p.add_argument("--gas", default="21000")
    build_p.add_argument("--data", default="0x")
    build_p.add_argument("--out")
    build_p.set_defaults(func=cmd_build)

    send_p = sub.add_parser("send", help="Legacy: build/send (prefer tx build)")
    send_p.add_argument("target")
    send_p.add_argument("--value", required=True)
    send_p.add_argument("--gas", default="21000")
    send_p.add_argument("--dry-run", action="store_true", default=False)
    send_p.add_argument("--out")
    send_p.set_defaults(func=cmd_send)

    sign_p = sub.add_parser("sign")
    sign_p.add_argument("raw_tx")
    sign_p.add_argument("--module", default=os.environ.get("TX_SIGN_MODULE", "EnvSigner"),
                        help="EnvSigner | KeyVaultSigner | SafeSigner")
    sign_p.add_argument("--vault-key", help="Key name when --module=KeyVaultSigner")
    sign_p.add_argument("--debug", action="store_true")
    sign_p.add_argument("--out")
    sign_p.set_defaults(func=cmd_sign)

    bc_p = sub.add_parser("broadcast")
    bc_p.add_argument("signed_tx")
    bc_p.add_argument("--force", action="store_true")
    bc_p.set_defaults(func=cmd_broadcast)

    st_p = sub.add_parser("status")
    st_p.add_argument("hash")
    st_p.add_argument("--json", action="store_true", default=True)
    st_p.set_defaults(func=cmd_status)

    rescue_p = sub.add_parser("rescue", help="SAFE → GAS_HOLDER top-up")
    rescue_p.add_argument("--target", help="GAS_HOLDER address")
    rescue_p.add_argument("--value", default="0.01bnb")
    rescue_p.add_argument("--gas", default="21000")
    rescue_p.add_argument("--dry-run", action="store_true", default=False)
    rescue_p.set_defaults(func=cmd_rescue)

    args = parser.parse_args()
    if args.cmd == "send" and not _live_enabled():
        if not args.dry_run and "--dry-run" not in sys.argv:
            args.dry_run = True
    if args.cmd == "rescue" and not _live_enabled():
        if not args.dry_run and "--dry-run" not in sys.argv:
            args.dry_run = True
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
