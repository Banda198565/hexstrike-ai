#!/usr/bin/env python3
"""
Dummy signing bot for local Anvil sandbox (Step 1).

Polls eth_getBalance every N seconds. When balance drops below THRESHOLD_WEI,
signs and broadcasts a small test transaction with the bot's private key.

Set HARDENING_ENABLED=true for Step 3 defensive checks (multi-RPC, anomaly guard).

LOCAL SANDBOX ONLY — uses Anvil's public test keys from anvil.env.example.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
DEFAULT_ENV = SANDBOX / "anvil.env.example"
ARTIFACT = ROOT / "artifacts" / "sandbox" / "dummy-bot-events.jsonl"

sys.path.insert(0, str(SANDBOX))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dummy-bot] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dummy-bot")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


@dataclass(frozen=True)
class BotConfig:
    rpc_url: str
    direct_rpc_url: str
    bot_address: str
    bot_private_key: str
    funder_address: str
    threshold_wei: int
    min_gas_wei: int
    rescue_value_wei: int
    poll_interval_sec: float
    dry_run: bool
    hardening: bool

    @classmethod
    def from_env(cls) -> BotConfig:
        return cls(
            rpc_url=os.environ.get("RPC_URL", "http://127.0.0.1:8545"),
            direct_rpc_url=os.environ.get(
                "DIRECT_RPC_URL", os.environ.get("UPSTREAM_RPC", "http://127.0.0.1:8545")
            ),
            bot_address=os.environ["BOT_ADDRESS"],
            bot_private_key=os.environ["BOT_PRIVATE_KEY"],
            funder_address=os.environ.get("FUNDER_ADDRESS", "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"),
            threshold_wei=int(os.environ.get("THRESHOLD_WEI", "500000000000000000")),
            min_gas_wei=int(os.environ.get("MIN_GAS_WEI", "10000000000000000")),
            rescue_value_wei=int(os.environ.get("RESCUE_VALUE_WEI", "1000000000000000")),
            poll_interval_sec=float(os.environ.get("POLL_INTERVAL_SEC", "10")),
            dry_run=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
            hardening=os.environ.get("HARDENING_ENABLED", "").lower() in ("1", "true", "yes"),
        )


def rpc_call(url: str, method: str, params: list[Any], timeout: float = 10.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def wei_to_eth(wei: int) -> str:
    return f"{wei / 1e18:.6f}"


def append_event(event: dict[str, Any]) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with ARTIFACT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def sign_rescue_tx_cast(cfg: BotConfig) -> str:
    sign_rpc = cfg.direct_rpc_url if cfg.hardening else cfg.rpc_url
    cmd = [
        "cast",
        "send",
        cfg.funder_address,
        "--private-key",
        cfg.bot_private_key,
        "--value",
        str(cfg.rescue_value_wei),
        "--rpc-url",
        sign_rpc,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    payload = json.loads(proc.stdout)
    return payload.get("transactionHash") or payload.get("hash") or proc.stdout.strip()


def sign_rescue_tx_eth_account(cfg: BotConfig) -> str:
    from eth_account import Account  # type: ignore[import-untyped]

    sign_rpc = cfg.direct_rpc_url if cfg.hardening else cfg.rpc_url
    acct = Account.from_key(cfg.bot_private_key)
    nonce = int(rpc_call(sign_rpc, "eth_getTransactionCount", [cfg.bot_address, "pending"]), 16)
    gas_price = int(rpc_call(sign_rpc, "eth_gasPrice", []), 16)
    chain_id = int(rpc_call(sign_rpc, "eth_chainId", []), 16)

    tx: dict[str, Any] = {
        "chainId": chain_id,
        "nonce": nonce,
        "to": cfg.funder_address,
        "value": cfg.rescue_value_wei,
        "gas": 21000,
        "maxFeePerGas": gas_price * 2,
        "maxPriorityFeePerGas": gas_price,
        "type": 2,
    }
    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction.hex()
    if not raw.startswith("0x"):
        raw = "0x" + raw
    return rpc_call(sign_rpc, "eth_sendRawTransaction", [raw])


def sign_rescue_tx(cfg: BotConfig) -> tuple[str, str]:
    if cfg.dry_run:
        return "dry-run", "skipped — DRY_RUN=1"

    if shutil_which("cast"):
        return "cast", sign_rescue_tx_cast(cfg)

    try:
        return "eth_account", sign_rescue_tx_eth_account(cfg)
    except ImportError:
        raise RuntimeError(
            "No signer available. Install Foundry (cast) or: pip install eth-account"
        ) from None


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def check_rpc(cfg: BotConfig) -> None:
    try:
        chain_id = int(rpc_call(cfg.rpc_url, "eth_chainId", []), 16)
        log.info("RPC OK — chain_id=%s url=%s", chain_id, cfg.rpc_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.error("RPC unreachable at %s — start Anvil: ./scripts/sandbox/start-anvil.sh", cfg.rpc_url)
        raise SystemExit(1) from exc


def run_once(cfg: BotConfig, guard_state: Any | None = None) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    event: dict[str, Any] = {
        "ts": ts,
        "event": "poll",
        "address": cfg.bot_address,
        "threshold_wei": cfg.threshold_wei,
        "hardening": cfg.hardening,
    }

    if cfg.hardening:
        from balance_guard import GuardConfig, GuardState, evaluate_poll, pre_sign_verify

        guard_cfg = GuardConfig(
            primary_rpc=cfg.rpc_url,
            direct_rpc=cfg.direct_rpc_url,
            address=cfg.bot_address,
            enabled=True,
        )
        state = guard_state if guard_state is not None else GuardState()
        checks = evaluate_poll(guard_cfg, state)
        balance = checks["use_balance_wei"]
        event.update(checks)

        log.info(
            "balance primary=%s direct=%s ETH match=%s",
            wei_to_eth(checks["primary_wei"]),
            wei_to_eth(checks["direct_wei"]),
            checks["balances_match"],
        )

        if checks["block_signing"]:
            event["action"] = "blocked"
            event["result"] = checks["block_reason"]
            log.error("BLOCKED by hardening: %s", checks["block_reason"])
            append_event(event)
            return
    else:
        bal_hex = rpc_call(cfg.rpc_url, "eth_getBalance", [cfg.bot_address, "latest"])
        balance = int(bal_hex, 16)
        log.info(
            "balance=%s ETH (%s wei) threshold=%s ETH",
            wei_to_eth(balance),
            balance,
            wei_to_eth(cfg.threshold_wei),
        )

    event["balance_wei"] = balance

    if balance >= cfg.threshold_wei:
        event["action"] = "none"
        append_event(event)
        return

    event["action"] = "trigger"
    log.warning("THRESHOLD HIT — balance below %s ETH", wei_to_eth(cfg.threshold_wei))

    if balance < cfg.min_gas_wei:
        event["result"] = "blocked_no_gas"
        log.error("Cannot sign — balance %s wei < MIN_GAS_WEI %s", balance, cfg.min_gas_wei)
        append_event(event)
        return

    if cfg.hardening:
        from balance_guard import GuardConfig, pre_sign_verify

        guard_cfg = GuardConfig(cfg.rpc_url, cfg.direct_rpc_url, cfg.bot_address, True)
        allowed, verify_detail = pre_sign_verify(guard_cfg, cfg.threshold_wei)
        event["pre_sign_verify"] = verify_detail
        if not allowed:
            event["result"] = "blocked_pre_sign_verify"
            log.error("BLOCKED pre-sign: direct RPC balance above threshold")
            append_event(event)
            return

    try:
        signer, tx_hash = sign_rescue_tx(cfg)
        event["result"] = "signed"
        event["signer"] = signer
        event["tx_hash"] = tx_hash
        log.info("Rescue tx sent via %s — hash=%s", signer, tx_hash)
    except Exception as exc:  # noqa: BLE001
        event["result"] = "error"
        event["error"] = str(exc)
        log.exception("Rescue tx failed: %s", exc)

    append_event(event)


def main() -> int:
    env_path = Path(os.environ.get("SANDBOX_ENV", DEFAULT_ENV))
    load_env_file(env_path)

    missing = [k for k in ("BOT_ADDRESS", "BOT_PRIVATE_KEY") if not os.environ.get(k)]
    if missing:
        log.error("Missing env vars: %s — copy scripts/sandbox/anvil.env.example", ", ".join(missing))
        return 1

    cfg = BotConfig.from_env()
    check_rpc(cfg)

    log.info(
        "Watching %s every %ss (threshold=%s ETH, dry_run=%s, hardening=%s)",
        cfg.bot_address,
        cfg.poll_interval_sec,
        wei_to_eth(cfg.threshold_wei),
        cfg.dry_run,
        cfg.hardening,
    )
    if cfg.hardening:
        log.info("Direct RPC (truth source): %s", cfg.direct_rpc_url)
        log.info("Alerts → %s", ROOT / "artifacts" / "sandbox" / "anomaly-alerts.jsonl")
    log.info("Events → %s", ARTIFACT)

    guard_state = None
    if cfg.hardening:
        from balance_guard import GuardState

        guard_state = GuardState()

    try:
        while True:
            run_once(cfg, guard_state)
            time.sleep(cfg.poll_interval_sec)
    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
