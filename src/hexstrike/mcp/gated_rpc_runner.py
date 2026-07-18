"""Gated RPC runner — read-only block/state/events/trace/simulate tools for orchestrator MCP."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexstrike.mcp.web3_rpc_runner import (
    _ADDR_RE,
    _KNOWN_TOPICS,
    _TX_RE,
    _checksum_address,
    _normalize_chain,
    _rpc_call,
    resolve_rpc_endpoint,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATED_CONFIG = _REPO_ROOT / "config" / "gated-mcp.json"
_ARTIFACTS = _REPO_ROOT / "artifacts" / "gated-rpc"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_gated_config() -> dict[str, Any]:
    if _GATED_CONFIG.is_file():
        return json.loads(_GATED_CONFIG.read_text(encoding="utf-8"))
    return {"rpc": {}}


def _write_artifact(name: str, payload: dict[str, Any]) -> str:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = _ARTIFACTS / name
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(out.relative_to(_REPO_ROOT))


def _parse_block_number(block_number: str) -> str:
    bn = block_number.strip().lower()
    if bn in ("latest", "pending", "earliest"):
        return bn
    if bn.startswith("0x"):
        return bn
    return hex(int(bn))


def _block_span(from_block: str, to_block: str) -> int | None:
    cfg = _load_gated_config().get("rpc", {})
    max_range = int(cfg.get("max_log_block_range") or 5000)
    if from_block in ("latest", "pending", "earliest") or to_block in ("latest", "pending", "earliest"):
        return None
    try:
        fb = int(from_block, 16) if from_block.startswith("0x") else int(from_block)
        tb = int(to_block, 16) if to_block.startswith("0x") else int(to_block)
        span = abs(tb - fb)
        if span > max_range:
            raise ValueError(f"block range {span} exceeds max_log_block_range ({max_range})")
        return span
    except ValueError:
        return None


def rpc_get_block(chain: str, block_number: str = "latest") -> dict[str, Any]:
    """Read-only block metadata — eth_getBlockByNumber."""
    req_id = f"gated-rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "request_id": req_id, "read_only": True}

    tag = _parse_block_number(block_number)
    resp = _rpc_call(endpoint["_url"], "eth_getBlockByNumber", [tag, False])
    if not resp.get("success") or not resp.get("result"):
        return {
            "success": False,
            "request_id": req_id,
            "error": resp.get("error") or "block not found",
            "read_only": True,
        }

    block = resp["result"]
    payload = {
        "success": True,
        "request_id": req_id,
        "chain": _normalize_chain(chain),
        "number": block.get("number"),
        "hash": block.get("hash"),
        "timestamp": block.get("timestamp"),
        "tx_count": len(block.get("transactions") or []),
        "gas_used": block.get("gasUsed"),
        "gas_limit": block.get("gasLimit"),
        "read_only": True,
    }
    payload["raw_report_path"] = _write_artifact(f"{req_id}-block.json", payload)
    return payload


def rpc_get_contract_state(
    chain: str,
    address: str,
    slot_keys: list[str],
    abi: str | None = None,
) -> dict[str, Any]:
    """Read-only storage slots — eth_getStorageAt per key."""
    req_id = f"gated-rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        addr = _checksum_address(address)
    except ValueError:
        return {"success": False, "request_id": req_id, "error": "invalid address", "read_only": True}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "request_id": req_id, "read_only": True}

    slots: list[dict[str, str]] = []
    url = endpoint["_url"]
    for key in slot_keys:
        slot_param = key if key.startswith("0x") else hex(int(key)) if key.isdigit() else key
        resp = _rpc_call(url, "eth_getStorageAt", [addr, slot_param, "latest"])
        raw = resp.get("result") if resp.get("success") else None
        entry: dict[str, str] = {"key": key, "raw_value": raw or "0x0", "decoded_value": raw or "0x0"}
        if abi:
            entry["abi_provided"] = "true"
        slots.append(entry)

    payload = {
        "success": True,
        "request_id": req_id,
        "address": addr,
        "chain": _normalize_chain(chain),
        "slots": slots,
        "read_only": True,
    }
    payload["raw_report_path"] = _write_artifact(f"{req_id}-state.json", payload)
    return payload


def rpc_get_events(
    chain: str,
    address: str,
    from_block: str,
    to_block: str,
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only event logs — eth_getLogs with server-side range cap."""
    req_id = f"gated-rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        addr = _checksum_address(address)
    except ValueError:
        return {"success": False, "request_id": req_id, "error": "invalid address", "read_only": True}

    try:
        _block_span(from_block, to_block)
    except ValueError as exc:
        return {"success": False, "request_id": req_id, "error": str(exc), "read_only": True}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "request_id": req_id, "read_only": True}

    filter_obj: dict[str, Any] = {
        "address": addr,
        "fromBlock": _parse_block_number(from_block) if from_block != "latest" else from_block,
        "toBlock": _parse_block_number(to_block) if to_block != "latest" else to_block,
    }
    if topics:
        filter_obj["topics"] = [t if t.startswith("0x") else t for t in topics]

    resp = _rpc_call(endpoint["_url"], "eth_getLogs", [filter_obj])
    if not resp.get("success"):
        return {"success": False, "request_id": req_id, "error": resp.get("error"), "read_only": True}

    logs = resp.get("result") or []
    if not isinstance(logs, list):
        logs = []

    cfg = _load_gated_config().get("rpc", {})
    max_events = int(cfg.get("max_events_returned") or 500)
    truncated = len(logs) > max_events
    if truncated:
        logs = logs[:max_events]

    events: list[dict[str, Any]] = []
    for log in logs:
        topics_list = log.get("topics") or []
        t0 = topics_list[0].lower() if topics_list else ""
        events.append(
            {
                "tx_hash": log.get("transactionHash"),
                "block_number": log.get("blockNumber"),
                "event_name": _KNOWN_TOPICS.get(t0, "unknown"),
                "data": {
                    "topics": topics_list,
                    "data": log.get("data"),
                    "log_index": log.get("logIndex"),
                },
            }
        )

    payload = {
        "success": True,
        "request_id": req_id,
        "chain": _normalize_chain(chain),
        "address": addr,
        "event_count": len(events),
        "truncated": truncated,
        "events": events,
        "read_only": True,
    }
    payload["raw_report_path"] = _write_artifact(f"{req_id}-events.json", payload)
    return payload


def _flatten_trace(node: dict[str, Any], depth: int = 0) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = [
        {
            "from": node.get("from"),
            "to": node.get("to"),
            "value": node.get("value"),
            "input": node.get("input"),
            "output": node.get("output"),
            "depth": depth,
            "type": node.get("type"),
        }
    ]
    for child in node.get("calls") or []:
        if isinstance(child, dict):
            frames.extend(_flatten_trace(child, depth + 1))
    return frames


def rpc_trace_transaction(
    chain: str,
    tx_hash: str,
    trace_type: str = "call",
) -> dict[str, Any]:
    """Read-only transaction trace — debug_traceTransaction when RPC supports it."""
    req_id = f"gated-rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    if not _TX_RE.match(tx_hash.strip()):
        return {"success": False, "request_id": req_id, "error": "invalid tx hash", "read_only": True}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "request_id": req_id, "read_only": True}

    tx_hash = tx_hash.strip().lower()
    tracer = "callTracer" if trace_type == "call" else trace_type
    resp = _rpc_call(endpoint["_url"], "debug_traceTransaction", [tx_hash, {"tracer": tracer}])
    frames: list[dict[str, Any]] = []
    if resp.get("success") and isinstance(resp.get("result"), dict):
        frames = _flatten_trace(resp["result"])

    payload = {
        "success": bool(frames) or resp.get("success", False),
        "request_id": req_id,
        "tx_hash": tx_hash,
        "trace_type": trace_type,
        "frames": frames,
        "frame_count": len(frames),
        "trace_available": bool(frames),
        "error": None if frames else (resp.get("error") or "trace not available on RPC"),
        "read_only": True,
    }
    payload["raw_report_path"] = _write_artifact(f"{req_id}-trace.json", payload)
    return payload


def rpc_simulate_call(
    chain: str,
    to: str,
    data: str = "0x",
    from_address: str = "0x0000000000000000000000000000000000000000",
    value: str = "0x0",
) -> dict[str, Any]:
    """Read-only eth_call simulation — never broadcasts."""
    req_id = f"gated-rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        to_addr = _checksum_address(to)
    except ValueError:
        return {"success": False, "request_id": req_id, "error": "invalid to address", "read_only": True}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "request_id": req_id, "read_only": True}

    call_obj = {
        "from": from_address,
        "to": to_addr,
        "data": data if data.startswith("0x") else f"0x{data}",
        "value": value if value.startswith("0x") else hex(int(value)),
    }
    resp = _rpc_call(endpoint["_url"], "eth_call", [call_obj, "latest"])
    if not resp.get("success"):
        return {
            "success": False,
            "request_id": req_id,
            "error": resp.get("error"),
            "read_only": True,
            "simulation_only": True,
        }

    return_data = resp.get("result") or "0x"
    payload = {
        "success": True,
        "request_id": req_id,
        "chain": _normalize_chain(chain),
        "return_data": return_data,
        "reverted": return_data == "0x" and False,
        "error": None,
        "simulation_only": True,
        "read_only": True,
        "note": "eth_call only — no eth_sendTransaction",
    }
    payload["raw_report_path"] = _write_artifact(f"{req_id}-simulate.json", payload)
    return payload
