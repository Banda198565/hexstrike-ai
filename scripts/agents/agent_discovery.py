#!/usr/bin/env python3
"""Agent-Discovery-01 — read-only blockchain findings (wallets, contracts, activity)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv
from crypto_rpc_orchestrator import load_config, rpc_call

load_dotenv(ROOT / ".env")

LOG = ROOT / "artifacts" / "agents" / "discovery_agent.log"
OUT = ROOT / "artifacts" / "agents" / "discovery_findings.json"
RPC_CFG = ROOT / "config" / "rpc_config.json"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}\n")


def _rpc() -> str:
    cfg = load_config(RPC_CFG)
    return os.environ.get("RPC_URL") or cfg["primary"]


def probe_address(rpc: str, addr: str) -> dict[str, Any]:
    addr = addr if addr.startswith("0x") else f"0x{addr}"
    bal_wei = int(rpc_call(rpc, "eth_getBalance", [addr, "latest"])["result"], 16)
    nonce = int(rpc_call(rpc, "eth_getTransactionCount", [addr, "latest"])["result"], 16)
    code = rpc_call(rpc, "eth_getCode", [addr, "latest"]).get("result", "0x")
    is_contract = code not in ("0x", "0x0", "")
    finding: dict[str, Any] = {
        "address": addr,
        "balance_bnb": round(bal_wei / 1e18, 8),
        "nonce": nonce,
        "is_contract": is_contract,
        "code_bytes": max(0, (len(code) - 2) // 2) if code.startswith("0x") else 0,
    }
    # Defensive heuristics only — no exploit guidance
    tags: list[str] = []
    if not is_contract and nonce == 0 and bal_wei > 0:
        tags.append("eoa_unused_nonce")
    if is_contract and finding["code_bytes"] < 100:
        tags.append("minimal_contract_bytecode")
    if bal_wei == 0 and nonce > 0:
        tags.append("active_empty_wallet")
    finding["tags"] = tags
    return finding


def run(mode: str = "scan") -> dict:
    rpc = _rpc()
    cfg = load_config(RPC_CFG)
    targets = list(cfg.get("monitoring", {}).get("target_contracts", []))
    hot = os.environ.get("TARGET_WALLET", "")
    if hot and hot not in targets:
        targets.insert(0, hot)

    _log(f"mode={mode} rpc={rpc} targets={len(targets)}")
    findings: list[dict] = []
    for addr in targets:
        try:
            findings.append(probe_address(rpc, addr))
        except Exception as exc:  # noqa: BLE001
            findings.append({"address": addr, "error": str(exc)})

    block = rpc_call(rpc, "eth_blockNumber", [])["result"]
    block_num = int(block, 16)
    recent_txs: list[str] = []
    if mode == "trace":
        for i in range(min(3, block_num + 1)):
            bn = hex(block_num - i)
            blk = rpc_call(rpc, "eth_getBlockByNumber", [bn, True]).get("result") or {}
            for tx in (blk.get("transactions") or [])[:5]:
                if isinstance(tx, dict):
                    recent_txs.append(tx.get("hash", ""))

    alerts = [f for f in findings if f.get("tags")]
    result = {
        "agent": "discovery",
        "agent_id": "Agent-Discovery-01",
        "mode": mode,
        "rpc": rpc,
        "block": block,
        "findings": findings,
        "alerts": alerts,
        "recent_tx_hashes": recent_txs,
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    mode = os.environ.get("HEXSTRIKE_TASK", sys.argv[1] if len(sys.argv) > 1 else "scan")
    return 0 if run(mode).get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
