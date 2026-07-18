"""Web3 RPC scanner runner — read-only JSON-RPC via env-injected keys (never in agent prompt)."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from hexstrike.paths import ROOT, RPC_CONFIG

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = _REPO_ROOT / "artifacts" / "web3-rpc"
_CHAINS_CONFIG = _REPO_ROOT / "config" / "web3-rpc-chains.json"

_EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

# EVM opcode hex (bytecode body) — defensive pattern flags only
_DANGEROUS_OPCODE_FLAGS: dict[str, str] = {
    "f4": "DELEGATECALL",
    "ff": "SELFDESTRUCT",
    "f1": "CALL",
    "f2": "CALLCODE",
    "fa": "STATICCALL",
}

# Common event topic0 hashes (keccak256 signatures)
_KNOWN_TOPICS: dict[str, str] = {
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef": "Transfer(address,address,uint256)",
    "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925": "Approval(address,address,uint256)",
    "0x17307eab39ab6107e8899845ad3d59bd9653f200f220920489ca2b5937696c31": "ApprovalForAll(address,address,bool)",
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_chains_config() -> dict[str, Any]:
    if _CHAINS_CONFIG.is_file():
        return json.loads(_CHAINS_CONFIG.read_text(encoding="utf-8"))
    return {"chains": {}, "public_fallbacks": {}}


def _normalize_chain(chain: str) -> str:
    c = chain.strip().lower()
    cfg = _load_chains_config()
    for name, meta in cfg.get("chains", {}).items():
        if c == name or c in (meta.get("aliases") or []):
            return name
    return c


def _chain_env_suffix(chain: str) -> str:
    return _normalize_chain(chain).upper().replace("-", "_")


def resolve_rpc_endpoint(chain: str = "mainnet") -> dict[str, Any]:
    """Build RPC URL from WEB3_RPC_URL/WEB3_RPC_KEY env (key never returned)."""
    chain = _normalize_chain(chain)
    suffix = _chain_env_suffix(chain)
    base_url = os.getenv(f"WEB3_RPC_URL_{suffix}") or os.getenv("WEB3_RPC_URL")
    api_key = os.getenv(f"WEB3_RPC_KEY_{suffix}") or os.getenv("WEB3_RPC_KEY", "")

    source = "env"
    if not base_url:
        cfg = _load_chains_config()
        base_url = cfg.get("public_fallbacks", {}).get(chain)
        source = "public_fallback"
    if not base_url and RPC_CONFIG.is_file():
        rpc_cfg = json.loads(RPC_CONFIG.read_text(encoding="utf-8"))
        base_url = rpc_cfg.get("primary")
        source = "rpc_config.json"

    if not base_url:
        return {
            "success": False,
            "error": "no RPC URL — set WEB3_RPC_URL or WEB3_RPC_URL_<CHAIN> in MCP server env",
            "chain": chain,
        }

    url = base_url.rstrip("/")
    if api_key and api_key not in url:
        # Infura/Alchemy/Chainstack: append key path segment
        url = f"{url}/{api_key.lstrip('/')}"

    return {
        "success": True,
        "chain": chain,
        "rpc_url_redacted": _redact_url(url),
        "has_api_key": bool(api_key),
        "source": source,
        "_url": url,
    }


def _redact_url(url: str) -> str:
    """Hide API key segments in URL for agent-visible output."""
    parts = url.rstrip("/").split("/")
    _safe_segments = {"v1", "v2", "v3", "mainnet", "jsonrpc", "eth"}
    if len(parts) >= 2:
        last = parts[-1]
        if last.lower() not in _safe_segments and len(last) >= 8:
            parts[-1] = "***REDACTED***"
            return "/".join(parts)
    if "?" in url:
        base, qs = url.split("?", 1)
        if "apikey=" in qs.lower() or "key=" in qs.lower():
            return base + "?***REDACTED***"
    return url.split("?")[0]


def _rpc_call(url: str, method: str, params: list[Any] | None = None, timeout: float = 12.0) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
    resp = requests.post(url, json=payload, timeout=timeout, headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        return {"success": False, "error": data["error"], "result": None}
    return {"success": True, "result": data.get("result"), "error": None}


def _checksum_address(address: str) -> str:
    addr = address.strip()
    if not _ADDR_RE.match(addr):
        raise ValueError("invalid address")
    return "0x" + addr[2:].lower()


def _analyze_bytecode(code_hex: str) -> dict[str, Any]:
    body = code_hex[2:] if code_hex.startswith("0x") else code_hex
    flags: list[dict[str, str]] = []
    seen: set[str] = set()
    for i in range(0, len(body) - 1, 2):
        op = body[i : i + 2].lower()
        if op in _DANGEROUS_OPCODE_FLAGS and op not in seen:
            seen.add(op)
            flags.append({"opcode": op, "name": _DANGEROUS_OPCODE_FLAGS[op]})
    return {
        "bytecode_length": len(body) // 2,
        "dangerous_opcodes": flags,
        "is_minimal_proxy": body.startswith("363d3d373d3d3d363d73") if body else False,
    }


def rpc_contract_audit(address: str, chain: str = "mainnet") -> dict[str, Any]:
    """Read-only contract audit by address: bytecode, proxy hints, opcode flags."""
    audit_id = f"rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        addr = _checksum_address(address)
    except ValueError:
        return {"success": False, "error": "invalid address", "audit_id": audit_id}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "audit_id": audit_id}

    url = endpoint["_url"]
    try:
        code_resp = _rpc_call(url, "eth_getCode", [addr, "latest"])
        if not code_resp.get("success"):
            return {"success": False, "audit_id": audit_id, "error": code_resp.get("error"), "read_only": True}

        code = code_resp.get("result") or "0x"
        analysis = _analyze_bytecode(code)
        is_contract = analysis["bytecode_length"] > 0

        is_proxy = False
        implementation_address: str | None = None
        if is_contract:
            slot_resp = _rpc_call(url, "eth_getStorageAt", [addr, _EIP1967_IMPL_SLOT, "latest"])
            if slot_resp.get("success"):
                slot_val = slot_resp.get("result") or "0x" + "0" * 64
                if int(slot_val, 16) != 0:
                    is_proxy = True
                    implementation_address = "0x" + slot_val[-40:]

        findings: list[dict[str, Any]] = []
        for op in analysis["dangerous_opcodes"]:
            findings.append(
                {
                    "type": f"opcode-{op['name'].lower()}",
                    "severity": "high" if op["name"] in ("DELEGATECALL", "SELFDESTRUCT") else "medium",
                    "description": f"Bytecode contains {op['name']} opcode ({op['opcode']}) — review trust boundaries",
                }
            )
        if analysis["is_minimal_proxy"]:
            findings.append(
                {
                    "type": "minimal-proxy",
                    "severity": "medium",
                    "description": "EIP-1167 minimal proxy pattern detected — audit implementation separately",
                }
            )
        if is_proxy and implementation_address:
            findings.append(
                {
                    "type": "eip1967-proxy",
                    "severity": "info",
                    "description": f"EIP-1967 proxy; implementation {implementation_address}",
                }
            )

        payload = {
            "success": True,
            "audit_id": audit_id,
            "address": addr,
            "chain": _normalize_chain(chain),
            "is_contract": is_contract,
            "rpc_url_redacted": endpoint["rpc_url_redacted"],
            "bytecode_length": analysis["bytecode_length"],
            "dangerous_opcodes": analysis["dangerous_opcodes"],
            "is_proxy": is_proxy,
            "implementation_address": implementation_address,
            "findings": findings,
            "finding_count": len(findings),
            "read_only": True,
        }
        out_path = DEFAULT_ARTIFACTS / f"{audit_id}-contract-audit.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["raw_report_path"] = str(out_path)
        return payload
    except requests.RequestException as exc:
        return {"success": False, "audit_id": audit_id, "error": str(exc), "read_only": True}


def rpc_tx_trace(tx_hash: str, chain: str = "mainnet") -> dict[str, Any]:
    """Read-only tx analysis: receipt, input decode hints, trace if RPC supports debug_*."""
    audit_id = f"rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    if not _TX_RE.match(tx_hash.strip()):
        return {"success": False, "error": "invalid tx hash", "audit_id": audit_id}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "audit_id": audit_id}

    url = endpoint["_url"]
    tx_hash = tx_hash.strip().lower()
    suspicious_steps: list[dict[str, Any]] = []

    try:
        tx_resp = _rpc_call(url, "eth_getTransactionByHash", [tx_hash])
        rcpt_resp = _rpc_call(url, "eth_getTransactionReceipt", [tx_hash])
        tx = tx_resp.get("result") if tx_resp.get("success") else None
        receipt = rcpt_resp.get("result") if rcpt_resp.get("success") else None

        if not tx:
            return {"success": False, "audit_id": audit_id, "error": "transaction not found", "read_only": True}

        input_data = (tx.get("input") or "0x")[2:]
        if len(input_data) >= 8:
            selector = "0x" + input_data[:8]
        else:
            selector = "0x"

        # Heuristic: value transfer + short input = plain ETH send
        if int(tx.get("value") or "0x0", 16) > 0 and len(input_data) <= 8:
            suspicious_steps.append(
                {
                    "step": "native_transfer",
                    "severity": "info",
                    "detail": "Transaction carries native token value",
                }
            )

        # Try debug trace (often unavailable on public RPC — not an error)
        trace_skipped = True
        trace_skip_reason = "debug_traceTransaction not available on this RPC"
        trace_resp = _rpc_call(url, "debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
        if trace_resp.get("success") and trace_resp.get("result"):
            trace_skipped = False
            trace = trace_resp["result"]

            def _walk_trace(node: dict[str, Any], depth: int = 0) -> None:
                typ = (node.get("type") or "").lower()
                if typ in ("delegatecall", "callcode"):
                    suspicious_steps.append(
                        {
                            "step": typ,
                            "severity": "high",
                            "detail": f"{typ} to {node.get('to')}",
                            "depth": depth,
                        }
                    )
                if node.get("error"):
                    suspicious_steps.append(
                        {
                            "step": "revert",
                            "severity": "medium",
                            "detail": str(node.get("error")),
                            "depth": depth,
                        }
                    )
                for child in node.get("calls") or []:
                    if isinstance(child, dict):
                        _walk_trace(child, depth + 1)

            if isinstance(trace, dict):
                _walk_trace(trace)

        if receipt:
            status = int(receipt.get("status") or "0x0", 16)
            if status == 0:
                suspicious_steps.append(
                    {"step": "tx_reverted", "severity": "info", "detail": "Transaction reverted on-chain"}
                )
            logs = receipt.get("logs") or []
            if len(logs) > 50:
                suspicious_steps.append(
                    {
                        "step": "high_log_volume",
                        "severity": "medium",
                        "detail": f"{len(logs)} logs emitted — review for spam/airdrop patterns",
                    }
                )

        payload = {
            "success": True,
            "audit_id": audit_id,
            "tx_hash": tx_hash,
            "chain": _normalize_chain(chain),
            "from": tx.get("from"),
            "to": tx.get("to"),
            "value_wei_hex": tx.get("value"),
            "input_selector": selector,
            "block_number": tx.get("blockNumber"),
            "suspicious_steps": suspicious_steps,
            "suspicious_step_count": len(suspicious_steps),
            "trace_skipped": trace_skipped,
            "trace_skip_reason": trace_skip_reason if trace_skipped else None,
            "read_only": True,
        }
        out_path = DEFAULT_ARTIFACTS / f"{audit_id}-tx-trace.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["raw_report_path"] = str(out_path)
        return payload
    except requests.RequestException as exc:
        return {"success": False, "audit_id": audit_id, "error": str(exc), "read_only": True}


def rpc_wallet_risk(address: str, chain: str = "mainnet") -> dict[str, Any]:
    """Read-only wallet/address risk triage: contract vs EOA, balance, nonce, heuristic flags."""
    audit_id = f"rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        addr = _checksum_address(address)
    except ValueError:
        return {"success": False, "error": "invalid address", "audit_id": audit_id}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "audit_id": audit_id}

    url = endpoint["_url"]
    risk_flags: list[dict[str, Any]] = []
    risk_score = 0

    try:
        code_resp = _rpc_call(url, "eth_getCode", [addr, "latest"])
        bal_resp = _rpc_call(url, "eth_getBalance", [addr, "latest"])
        nonce_resp = _rpc_call(url, "eth_getTransactionCount", [addr, "latest"])

        code = (code_resp.get("result") or "0x") if code_resp.get("success") else "0x"
        body = code[2:] if code.startswith("0x") else code
        is_contract = len(body) > 0
        balance = int(bal_resp.get("result") or "0x0", 16) if bal_resp.get("success") else 0
        nonce = int(nonce_resp.get("result") or "0x0", 16) if nonce_resp.get("success") else 0

        if is_contract:
            analysis = _analyze_bytecode(code)
            if analysis["dangerous_opcodes"]:
                risk_flags.append(
                    {
                        "flag": "contract-dangerous-opcodes",
                        "severity": "medium",
                        "detail": [o["name"] for o in analysis["dangerous_opcodes"]],
                    }
                )
                risk_score += 15
            if analysis["is_minimal_proxy"]:
                risk_flags.append(
                    {"flag": "minimal-proxy", "severity": "low", "detail": "EIP-1167 clone — verify implementation"}
                )
                risk_score += 5
        else:
            if nonce == 0 and balance > 0:
                risk_flags.append(
                    {
                        "flag": "fresh-funder",
                        "severity": "medium",
                        "detail": "EOA with balance but zero outgoing nonce — possible disposable funder",
                    }
                )
                risk_score += 10
            if nonce > 5000:
                risk_flags.append(
                    {
                        "flag": "high-activity-eoa",
                        "severity": "info",
                        "detail": f"High nonce ({nonce}) — bot/CEX/service wallet candidate",
                    }
                )

        risk_score = min(100, risk_score)
        payload = {
            "success": True,
            "audit_id": audit_id,
            "address": addr,
            "chain": _normalize_chain(chain),
            "is_contract": is_contract,
            "balance_wei": balance,
            "nonce": nonce,
            "risk_flags": risk_flags,
            "risk_score": risk_score,
            "risk_level": "high" if risk_score >= 40 else "medium" if risk_score >= 15 else "low",
            "read_only": True,
            "_disclaimer": "Heuristic RPC triage only — full scam graph requires explorer/indexer API",
        }
        out_path = DEFAULT_ARTIFACTS / f"{audit_id}-wallet-risk.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["raw_report_path"] = str(out_path)
        return payload
    except requests.RequestException as exc:
        return {"success": False, "audit_id": audit_id, "error": str(exc), "read_only": True}


def rpc_event_intel(
    address: str,
    chain: str = "mainnet",
    topic: str | None = None,
    from_block: str = "latest",
    to_block: str = "latest",
) -> dict[str, Any]:
    """Read-only eth_getLogs aggregation for anomaly hints."""
    audit_id = f"rpc-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    try:
        addr = _checksum_address(address)
    except ValueError:
        return {"success": False, "error": "invalid address", "audit_id": audit_id}

    endpoint = resolve_rpc_endpoint(chain)
    if not endpoint.get("success"):
        return {**endpoint, "audit_id": audit_id}

    url = endpoint["_url"]
    filter_obj: dict[str, Any] = {
        "address": addr,
        "fromBlock": from_block,
        "toBlock": to_block,
    }
    if topic:
        filter_obj["topics"] = [topic if topic.startswith("0x") else topic]

    try:
        logs_resp = _rpc_call(url, "eth_getLogs", [filter_obj])
        if not logs_resp.get("success"):
            return {
                "success": False,
                "audit_id": audit_id,
                "error": logs_resp.get("error"),
                "read_only": True,
            }

        logs = logs_resp.get("result") or []
        if not isinstance(logs, list):
            logs = []

        by_topic: dict[str, int] = {}
        anomalies: list[dict[str, Any]] = []
        for log in logs:
            topics = log.get("topics") or []
            t0 = topics[0] if topics else "unknown"
            by_topic[t0] = by_topic.get(t0, 0) + 1

        topic_summary = [
            {
                "topic0": t0,
                "count": count,
                "signature": _KNOWN_TOPICS.get(t0.lower(), "unknown"),
            }
            for t0, count in sorted(by_topic.items(), key=lambda x: -x[1])
        ]

        if len(logs) > 100:
            anomalies.append(
                {
                    "type": "log_burst",
                    "severity": "medium",
                    "detail": f"{len(logs)} logs in range — possible spam/mint burst",
                }
            )
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        transfers = by_topic.get(transfer_topic, 0)
        if transfers > 50:
            anomalies.append(
                {
                    "type": "transfer_spike",
                    "severity": "medium",
                    "detail": f"{transfers} Transfer events in range",
                }
            )

        payload = {
            "success": True,
            "audit_id": audit_id,
            "address": addr,
            "chain": _normalize_chain(chain),
            "from_block": from_block,
            "to_block": to_block,
            "log_count": len(logs),
            "topic_summary": topic_summary,
            "anomalies": anomalies,
            "read_only": True,
        }
        out_path = DEFAULT_ARTIFACTS / f"{audit_id}-event-intel.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["raw_report_path"] = str(out_path)
        return payload
    except requests.RequestException as exc:
        return {"success": False, "audit_id": audit_id, "error": str(exc), "read_only": True}


def detect_rpc_config() -> dict[str, Any]:
    """Report RPC env configuration status — never exposes keys."""
    chains = list(_load_chains_config().get("chains", {}).keys()) or ["mainnet"]
    statuses: list[dict[str, Any]] = []
    for chain in chains:
        ep = resolve_rpc_endpoint(chain)
        statuses.append(
            {
                "chain": chain,
                "configured": ep.get("success", False),
                "source": ep.get("source"),
                "has_api_key": ep.get("has_api_key", False),
                "rpc_url_redacted": ep.get("rpc_url_redacted"),
            }
        )
    global_url = bool(os.getenv("WEB3_RPC_URL"))
    global_key = bool(os.getenv("WEB3_RPC_KEY"))
    return {
        "success": True,
        "global_env": {"rpc_url_set": global_url, "rpc_key_set": global_key},
        "chains": statuses,
        "read_only": True,
    }
