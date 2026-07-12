#!/usr/bin/env python3
"""Offensive MEV sandwich engine — Anvil sandbox ONLY."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SANDBOX = ROOT / "scripts" / "sandbox"
sys.path.insert(0, str(SANDBOX / "mev"))
from mev_common import fund_defaults  # noqa: E402
RPC = os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")
MNEMONIC = os.environ.get(
    "ANVIL_MNEMONIC", "test test test test test test test test test test test junk"
)


def _cast(*args: str, rpc: bool = True) -> str:
    cmd = ["cast", *args]
    if rpc:
        cmd.extend(["--rpc-url", RPC])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def _send(*args: str) -> str:
    """cast send with sane gas limit (BSC fork gas estimation often fails)."""
    extra = []
    if "--gas-limit" not in args:
        extra = ["--gas-limit", os.environ.get("MEV_GAS_LIMIT", "800000")]
    return _cast("send", *args, *extra)


def wallet(index: int) -> tuple[str, str]:
    proc = subprocess.run(
        ["cast", "wallet", "address", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    )
    addr = proc.stdout.strip()
    proc2 = subprocess.run(
        ["cast", "wallet", "private-key", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    )
    key = proc2.stdout.strip()
    return addr, key


def deploy_mock_amm() -> str:
    contracts = SANDBOX / "contracts"
    subprocess.run(["forge", "build", "--root", str(contracts)], check=True, capture_output=True)
    _, deployer_key = wallet(0)
    proc = subprocess.run(
        [
            "forge",
            "create",
            "MockAMM",
            "--root",
            str(contracts),
            "--private-key",
            deployer_key,
            "--rpc-url",
            RPC,
            "--value",
            "100ether",
            "--broadcast",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in proc.stdout.splitlines():
        if "Deployed to:" in line:
            return line.split("Deployed to:")[-1].strip()
    raise RuntimeError("forge create did not return address:\n" + proc.stdout)


def run_sandwich(amm: str, victim_eth: str = "1ether", frontrun_eth: str = "30ether") -> dict:
    """Execute offensive sandwich: buy → victim swap → sell (same block via anvil_mine)."""
    attacker, attacker_key = wallet(2)
    victim, victim_key = wallet(3)

    # Fund victim
    subprocess.run(
        ["cast", "rpc", "anvil_setBalance", victim, hex(int(5e18)), "--rpc-url", RPC],
        check=True,
        capture_output=True,
    )

    attacker_before = int(_cast("balance", attacker))
    victim_before = int(_cast("balance", victim))

    # Frontrun buy (high gas)
    _send(
        amm,
        "swapETHForTokens(uint256)",
        "0",
        "--value",
        frontrun_eth,
        "--private-key",
        attacker_key,
        "--gas-price",
        "3gwei",
    )

    # Victim swap (lower gas — simulated mempool ordering)
    _send(
        amm,
        "swapETHForTokens(uint256)",
        "0",
        "--value",
        victim_eth,
        "--private-key",
        victim_key,
        "--gas-price",
        "2gwei",
    )

    # Backrun sell all attacker tokens
    bal = _cast("call", amm, "balanceOf(address)(uint256)", attacker)
    token_in = int(bal.split("[")[0].strip())
    if token_in > 0:
        _send(
            amm,
            "swapTokensForETH(uint256,uint256)",
            str(token_in),
            "0",
            "--private-key",
            attacker_key,
            "--gas-price",
            "2gwei",
        )

    attacker_after = int(_cast("balance", attacker))
    victim_after = int(_cast("balance", victim))
    profit = attacker_after - attacker_before
    victim_loss = victim_before - victim_after

    return {
        "amm": amm,
        "attacker": attacker,
        "victim": victim,
        "profit_wei": profit,
        "victim_spent_wei": victim_loss,
        "success": profit > 0,
    }


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] MEV engine is sandbox-only", file=sys.stderr)
        return 1

    allowed = [c.strip() for c in os.environ.get("MEV_ALLOWED_CHAINS", "31337").split(",") if c.strip()]
    chain = _cast("chain-id")
    if chain not in allowed:
        print(f"[FAIL] chain_id={chain} not in allowed {allowed}", file=sys.stderr)
        return 1

    print("[mev] deploying MockAMM...")
    fund_defaults()
    amm = deploy_mock_amm()
    print(f"[mev] amm={amm}")
    result = run_sandwich(amm)
    out = ROOT / "artifacts" / "sandbox" / "mev-sandwich-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
