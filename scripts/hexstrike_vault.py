#!/usr/bin/env python3
"""HexStrike vault CLI — init, store-key, list, status."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv
from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.vault.keystore import KeyVault, VaultError

load_dotenv(ROOT / ".env")


def _passphrase(args: argparse.Namespace) -> str:
    env = os.environ.get("VAULT_PASSPHRASE", "")
    if env:
        return env
    if getattr(args, "passphrase", None):
        return args.passphrase
    return getpass.getpass("Vault passphrase: ")


def cmd_init(args: argparse.Namespace) -> int:
    vault = KeyVault(bus=ContextBus(), prefer_ramdisk=not args.disk)
    pw = _passphrase(args)
    if vault.vault_path and vault.vault_path.is_file():
        vault.unlock(pw)
    else:
        vault.unlock(pw)
        vault._save(pw)
    out = {"command": "vault_init", "success": True, **vault.status()}
    print(json.dumps(out, indent=2))
    return 0


def cmd_store_key(args: argparse.Namespace) -> int:
    key = os.environ.get(args.key_env, "").strip()
    if not key and args.private_key:
        key = args.private_key.strip()
    if not key:
        raise SystemExit(f"Set {args.key_env} or pass --private-key")
    if not key.startswith("0x"):
        key = "0x" + key
    vault = KeyVault(bus=ContextBus(), prefer_ramdisk=not args.disk)
    pw = _passphrase(args)
    vault.unlock(pw)
    vault.store_key(args.name, key, pw)
    out = {"command": "vault_store_key", "success": True, "name": args.name, **vault.status()}
    print(json.dumps(out, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    vault = KeyVault(bus=ContextBus(), prefer_ramdisk=not args.disk)
    pw = _passphrase(args)
    vault.unlock(pw)
    print(json.dumps({"command": "vault_list", "keys": vault.list_key_names(), **vault.status()}, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    vault = KeyVault(bus=ContextBus(), prefer_ramdisk=not args.disk)
    st = vault.status()
    print(json.dumps({"command": "vault_status", **st}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="hexstrike vault")
    sub = p.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="Create empty encrypted vault")
    init_p.add_argument("--name", default="bot")
    init_p.add_argument("--passphrase")
    init_p.add_argument("--disk", action="store_true", help="Use disk instead of ramdisk")
    init_p.set_defaults(func=cmd_init)

    store_p = sub.add_parser("store-key", help="Store private key in vault")
    store_p.add_argument("name", help="Key name e.g. bot, safe")
    store_p.add_argument("--key-env", default="BOT_PRIVATE_KEY")
    store_p.add_argument("--private-key")
    store_p.add_argument("--passphrase")
    store_p.add_argument("--disk", action="store_true")
    store_p.set_defaults(func=cmd_store_key)

    list_p = sub.add_parser("list")
    list_p.add_argument("--passphrase")
    list_p.add_argument("--disk", action="store_true")
    list_p.set_defaults(func=cmd_list)

    st_p = sub.add_parser("status")
    st_p.add_argument("--disk", action="store_true")
    st_p.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        return args.func(args)
    except VaultError as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
