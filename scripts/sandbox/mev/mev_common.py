#!/usr/bin/env python3
"""Shared helpers for offensive MEV sandbox engines."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SANDBOX = ROOT / "scripts" / "sandbox"
CONTRACTS = SANDBOX / "contracts"
MNEMONIC = os.environ.get(
    "ANVIL_MNEMONIC", "test test test test test test test test test test test junk"
)


def rpc_url() -> str:
    return os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")


def require_anvil() -> str:
    url = rpc_url()
    proc = subprocess.run(
        ["cast", "chain-id", "--rpc-url", url], capture_output=True, text=True, check=True
    )
    cid = proc.stdout.strip()
    allowed = os.environ.get("MEV_ALLOWED_CHAINS", "31337,56").split(",")
    if cid not in allowed:
        raise RuntimeError(f"chain {cid} not in allowed {allowed}")
    return cid


def cast(*args: str, rpc: bool = True) -> str:
    cmd = ["cast", *args]
    if rpc:
        cmd.extend(["--rpc-url", rpc_url()])
    if args and args[0] == "send" and "--gas-limit" not in args:
        cmd.extend(["--gas-limit", os.environ.get("MEV_GAS_LIMIT", "800000")])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def fund_wallet(index: int, wei: int) -> None:
    addr, _ = wallet(index)
    subprocess.run(
        ["cast", "rpc", "anvil_setBalance", addr, hex(wei), "--rpc-url", rpc_url()],
        check=True,
        capture_output=True,
    )


def fund_defaults() -> None:
    """Re-fund Anvil mnemonic accounts after prior MEV steps drain balances."""
    top = int(500e18)
    for idx in range(6):
        fund_wallet(idx, top)


def wallet(index: int) -> tuple[str, str]:
    addr = subprocess.run(
        ["cast", "wallet", "address", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    key = subprocess.run(
        ["cast", "wallet", "private-key", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return addr, key


def forge_create(contract: str, *, value: str | None = None, ctor_args: list[str] | None = None) -> str:
    subprocess.run(["forge", "build", "--root", str(CONTRACTS)], check=True, capture_output=True)
    _, deployer_key = wallet(0)
    cmd = [
        "forge", "create", contract,
        "--root", str(CONTRACTS),
        "--private-key", deployer_key,
        "--rpc-url", rpc_url(),
        "--broadcast",
    ]
    if value:
        cmd.extend(["--value", value])
    if ctor_args:
        cmd.extend(["--constructor-args", *ctor_args])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in proc.stdout.splitlines():
        if "Deployed to:" in line:
            return line.split("Deployed to:")[-1].strip()
    raise RuntimeError(proc.stdout)


def parse_uint(raw: str) -> int:
    return int(raw.split("[")[0].strip())


def write_artifact(name: str, payload: dict) -> Path:
    out = ROOT / "artifacts" / "sandbox" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
