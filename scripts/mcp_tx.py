#!/usr/bin/env python3
"""MCP transaction skills — build, sign, broadcast, status, rescue, log, discovery."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv

load_dotenv(ROOT / ".env")

# Reuse hexstrike tx implementation
import hexstrike_tx as tx  # noqa: E402


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _telemetry_dir(run_id: str | None = None) -> Path:
    rid = run_id or os.environ.get("TX_RUN_ID") or _utc_run_id()
    d = ROOT / "tx_logs" / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, indent=2))
    return 0 if result.get("success", result.get("result") == "ok") else 1


def skill_build(
    *,
    target: str,
    value: str = "0.001bnb",
    gas: int = 21000,
    data: str = "0x",
    dry_run: bool = True,
    out: str | None = None,
) -> dict[str, Any]:
    rpc = tx._rpc_url()
    to_addr = target if target.startswith("0x") else f"0x{target}"
    value_wei = tx.parse_value(value)
    built = tx._build_tx(
        from_addr=tx._from_address(),
        to_addr=to_addr,
        value_wei=value_wei,
        gas=gas,
        rpc=rpc,
    )
    if data and data != "0x":
        built["data"] = data if data.startswith("0x") else f"0x{data}"

    from hexstrike.bus.context_bus import ContextBus
    from hexstrike.core.execution.broadcaster import ExecutionBroadcaster
    from hexstrike.paths import RPC_CONFIG

    pre = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).preflight(built)
    out_path = Path(out) if out else ROOT / "artifacts" / "tx" / "raw_tx.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"transaction": built}, indent=2) + "\n", encoding="utf-8")

    result: dict[str, Any] = {
        "skill": "TransactionBuilder",
        "skill_id": "tx_build",
        "success": pre.ok,
        "dry_run": dry_run,
        "rpc": rpc,
        "transaction": built,
        "raw_tx_path": str(out_path),
        "preflight": {
            "ok": pre.ok,
            "gas_estimate": pre.gas_estimate,
            "gas_price_wei": pre.gas_price_wei,
            "errors": pre.errors,
            "warnings": pre.warnings,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    skill_log(step="build", payload=result)
    return result


def skill_sign(
    *,
    raw_tx: str,
    key_env: str = "BOT_PRIVATE_KEY",
    module: str | None = None,
    vault_key: str | None = None,
    out: str | None = None,
) -> dict[str, Any]:
    raw_path = Path(raw_tx)
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tx_dict = data.get("transaction", data)
    rpc = tx._rpc_url()
    mod_name = module or ("KeyVaultSigner" if os.environ.get("VAULT_PASSPHRASE") else "EnvSigner")
    mod_name, pk = tx._resolve_signer_module(mod_name, vault_key=vault_key or key_env if mod_name == "KeyVaultSigner" else None)
    signed = tx._sign_tx_dict(tx_dict, private_key=pk, rpc=rpc)
    signed["signer_module"] = mod_name
    out_path = Path(out) if out else raw_path.with_name("signed_tx.json")
    out_path.write_text(json.dumps({"command": "sign", **signed}, indent=2) + "\n", encoding="utf-8")
    result = {
        "skill": "TransactionSigner",
        "skill_id": "tx_sign",
        "success": True,
        "from": signed.get("from"),
        "hash": signed.get("hash"),
        "raw": signed.get("raw"),
        "output": str(out_path),
        "signer_module": mod_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    skill_log(step="sign", payload={"hash": result.get("hash"), "output": result["output"]})
    return result


def skill_broadcast(*, signed_tx: str, force: bool = False) -> dict[str, Any]:
    live = os.environ.get("HEXSTRIKE_TX_LIVE", "").lower() in ("1", "true", "yes")
    if not live and not force:
        return {
            "skill": "TransactionBroadcaster",
            "skill_id": "tx_broadcast",
            "success": False,
            "error": "Broadcast blocked — set HEXSTRIKE_TX_LIVE=1 or pass --force",
            "dry_run": True,
        }

    data = json.loads(Path(signed_tx).read_text(encoding="utf-8"))
    raw_hex = data.get("raw") or data.get("signed_tx") or data.get("rawTransaction")
    if not raw_hex:
        return {"skill": "TransactionBroadcaster", "success": False, "error": "missing raw hex in signed_tx"}

    from hexstrike.bus.context_bus import ContextBus
    from hexstrike.core.execution.broadcaster import ExecutionBroadcaster
    from hexstrike.paths import PENDING_ACTION, RPC_CONFIG

    if force:
        pending = json.loads(PENDING_ACTION.read_text(encoding="utf-8")) if PENDING_ACTION.is_file() else {}
        pending.update({"status": "approved", "approved_by": "mcp tx broadcast --force", "action": "broadcast_tx"})
        PENDING_ACTION.parent.mkdir(parents=True, exist_ok=True)
        PENDING_ACTION.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")

    bc_result = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).broadcast(raw_hex, approved=force)
    result = {
        "skill": "TransactionBroadcaster",
        "skill_id": "tx_broadcast",
        "success": bool(bc_result.get("success")),
        **bc_result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    skill_log(step="broadcast", payload=result)
    return result


def skill_status(*, tx_hash: str, json_out: bool = True) -> dict[str, Any]:
    rpc = tx._rpc_url()
    h = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
    receipt = tx.rpc_call(rpc, "eth_getTransactionReceipt", [h]).get("result")
    tx_obj = tx.rpc_call(rpc, "eth_getTransactionByHash", [h]).get("result")
    state = "pending"
    if receipt:
        state = "success" if int(receipt.get("status", "0x0"), 16) == 1 else "fail"
    result = {
        "skill": "TransactionStatusChecker",
        "skill_id": "tx_status",
        "success": True,
        "hash": h,
        "state": state,
        "mined": receipt is not None,
        "rpc": rpc,
        "transaction": tx_obj,
        "receipt": receipt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    skill_log(step="status", payload={"hash": h, "state": state})
    return result


def skill_rescue(
    *,
    target: str | None = None,
    value: str = "0.01bnb",
    gas: int = 21000,
    dry_run: bool = True,
) -> dict[str, Any]:
    ns = argparse.Namespace(
        target=target,
        value=value,
        gas=str(gas),
        dry_run=dry_run,
    )
    # Delegate to hexstrike tx rescue (handles SAFE sign + broadcast when live)
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = tx.cmd_rescue(ns)
    try:
        result = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        result = {"stdout": buf.getvalue()}
    result["skill"] = "RescueHandler"
    result["skill_id"] = "tx_rescue"
    result["success"] = code == 0
    skill_log(step="rescue", payload={"target": target, "dry_run": dry_run, "success": result["success"]})
    return result


def skill_log(*, step: str, payload: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    log_dir = _telemetry_dir(run_id)
    log_path = log_dir / "mcp_tx.log"
    entry = {
        "step": step,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    latest = ROOT / "tx_logs" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "mcp_tx.log").write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {"skill": "TelemetryLogger", "skill_id": "tx_log", "success": True, "log_path": str(log_path), "run_id": log_dir.name}


def skill_discovery(*, mode: str = "trace", target: str | None = None) -> dict[str, Any]:
    if target:
        os.environ["TARGET_WALLET"] = target
    import importlib.util

    spec = importlib.util.spec_from_file_location("agent_discovery", ROOT / "scripts/agents/agent_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    result = mod.run(mode=mode)
    result["skill"] = "DiscoveryScanner"
    result["skill_id"] = "tx_discovery"
    skill_log(step="discovery", payload={"mode": mode, "alerts": len(result.get("alerts", []))})
    return result


def main() -> int:
    p = argparse.ArgumentParser(prog="hexstrike mcp tx")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="TransactionBuilder — raw payload")
    b.add_argument("--target", required=True)
    b.add_argument("--value", default="0.001bnb")
    b.add_argument("--gas", type=int, default=21000)
    b.add_argument("--data", default="0x")
    b.add_argument("--dry-run", action="store_true", default=True)
    b.add_argument("--live", action="store_true", help="Disable dry-run flag in output metadata")
    b.add_argument("--out")

    s = sub.add_parser("sign", help="TransactionSigner")
    s.add_argument("raw_tx")
    s.add_argument("--module", default=os.environ.get("TX_SIGN_MODULE", "EnvSigner"))
    s.add_argument("--vault-key")
    s.add_argument("--out")

    bc = sub.add_parser("broadcast", help="TransactionBroadcaster")
    bc.add_argument("signed_tx")
    bc.add_argument("--force", action="store_true")

    st = sub.add_parser("status", help="TransactionStatusChecker")
    st.add_argument("hash")
    st.add_argument("--json", action="store_true", default=True)

    r = sub.add_parser("rescue", help="RescueHandler")
    r.add_argument("--target")
    r.add_argument("--value", default="0.01bnb")
    r.add_argument("--gas", type=int, default=21000)
    r.add_argument("--dry-run", action="store_true", default=True)
    r.add_argument("--live", action="store_true")

    lg = sub.add_parser("log", help="TelemetryLogger")
    lg.add_argument("--step", required=True)
    lg.add_argument("--payload", help="JSON string")
    lg.add_argument("--run-id")

    d = sub.add_parser("discovery", help="DiscoveryScanner")
    d.add_argument("--mode", default="trace", choices=["scan", "trace"])
    d.add_argument("--target")
    d.add_argument("--trace", action="store_true", help="Alias for --mode trace")

    args = p.parse_args()

    if args.cmd == "build":
        dry = not args.live
        return _emit(skill_build(
            target=args.target,
            value=args.value,
            gas=args.gas,
            data=args.data,
            dry_run=dry,
            out=args.out,
        ))
    if args.cmd == "sign":
        return _emit(skill_sign(raw_tx=args.raw_tx, module=args.module, vault_key=args.vault_key, out=args.out))
    if args.cmd == "broadcast":
        return _emit(skill_broadcast(signed_tx=args.signed_tx, force=args.force))
    if args.cmd == "status":
        return _emit(skill_status(tx_hash=args.hash, json_out=args.json))
    if args.cmd == "rescue":
        dry = not args.live
        if os.environ.get("HEXSTRIKE_TX_LIVE", "").lower() not in ("1", "true", "yes") and not args.live:
            dry = True
        return _emit(skill_rescue(target=args.target, value=args.value, gas=args.gas, dry_run=dry))
    if args.cmd == "log":
        payload = json.loads(args.payload) if args.payload else {}
        return _emit(skill_log(step=args.step, payload=payload, run_id=args.run_id))
    if args.cmd == "discovery":
        mode = "trace" if args.trace else args.mode
        return _emit(skill_discovery(mode=mode, target=args.target))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
