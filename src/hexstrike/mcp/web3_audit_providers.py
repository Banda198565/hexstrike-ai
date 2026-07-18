"""External Web3 security API providers — env-gated, read-only, no fabricated findings."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import requests

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$", re.I)

# GoPlus chain id map (partial — extend as needed)
GOPLUS_CHAIN_IDS: dict[str, str] = {
    "mainnet": "1",
    "ethereum": "1",
    "eth": "1",
    "bsc": "56",
    "binance": "56",
    "polygon": "137",
    "matic": "137",
    "arbitrum": "42161",
    "base": "8453",
    "optimism": "10",
    "avalanche": "43114",
    "sepolia": "11155111",
}


def _finding(
    *,
    source: str,
    category: str,
    severity: str,
    description: str,
    finding_id: str | None = None,
    links: list[str] | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": finding_id or f"{source}:{category}",
        "source": source,
        "category": category,
        "severity": severity,
        "description": description,
        "links": links or [],
        "raw": raw,
    }


def _skipped(source: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "skipped": True,
        "skip_reason": reason,
        "source": source,
        "findings": [],
        "finding_count": 0,
        **extra,
    }


def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    resp = requests.get(url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_post(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    resp = requests.post(url, json=payload, headers=hdrs, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def goplus_contract_risk(address: str, chain: str = "mainnet") -> dict[str, Any]:
    """GoPlus token/contract security API (public read-only endpoint)."""
    addr = address.strip().lower()
    if not _ADDR_RE.match(addr):
        return {"success": False, "error": "invalid address", "source": "goplus"}

    chain_id = GOPLUS_CHAIN_IDS.get(chain.lower())
    if not chain_id:
        return _skipped("goplus", f"unsupported chain for GoPlus: {chain}", chain=chain)

    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}"
    try:
        data = _http_get(url)
        result = (data.get("result") or {}).get(addr.lower()) or (data.get("result") or {}).get(addr)
        if not result:
            return {
                "success": True,
                "source": "goplus",
                "address": addr,
                "chain": chain,
                "findings": [],
                "finding_count": 0,
                "raw": data,
            }

        findings: list[dict[str, Any]] = []
        risk_fields = [
            ("is_honeypot", "honeypot", "critical", "Honeypot pattern flagged by GoPlus"),
            ("is_blacklisted", "blacklist", "high", "Token/contract blacklisted"),
            ("is_mintable", "mintable", "medium", "Mint function may be active"),
            ("can_take_back_ownership", "ownership", "high", "Ownership can be reclaimed"),
            ("owner_change_balance", "owner-rug", "critical", "Owner can modify balances"),
            ("hidden_owner", "hidden-owner", "medium", "Hidden owner detected"),
            ("selfdestruct", "selfdestruct", "high", "Selfdestruct present"),
            ("is_proxy", "proxy", "info", "Proxy contract — audit implementation"),
            ("is_open_source", "closed-source", "medium", "Contract not open source on explorer"),
        ]
        for field, cat, default_sev, desc in risk_fields:
            val = result.get(field)
            if val == "1" or val is True:
                findings.append(_finding(source="goplus", category=cat, severity=default_sev, description=desc, raw={field: val}))
            elif field == "is_open_source" and val == "0":
                findings.append(_finding(source="goplus", category=cat, severity=default_sev, description=desc, raw={field: val}))

        buy_tax = result.get("buy_tax")
        sell_tax = result.get("sell_tax")
        if buy_tax and float(buy_tax or 0) > 0.1:
            findings.append(
                _finding(
                    source="goplus",
                    category="tax",
                    severity="medium",
                    description=f"High buy tax: {buy_tax}",
                    raw={"buy_tax": buy_tax},
                )
            )
        if sell_tax and float(sell_tax or 0) > 0.1:
            findings.append(
                _finding(
                    source="goplus",
                    category="tax",
                    severity="medium",
                    description=f"High sell tax: {sell_tax}",
                    raw={"sell_tax": sell_tax},
                )
            )

        return {
            "success": True,
            "source": "goplus",
            "address": addr,
            "chain": chain,
            "findings": findings,
            "finding_count": len(findings),
            "risk_score": min(100, len(findings) * 12),
            "raw_summary": {k: result.get(k) for k in ("is_honeypot", "is_proxy", "is_open_source", "buy_tax", "sell_tax")},
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "goplus", "error": str(exc), "findings": []}


def forta_get_alerts(
    *,
    address: str | None = None,
    tx_hash: str | None = None,
    chain: str = "mainnet",
) -> dict[str, Any]:
    """Forta bot alerts — requires FORTA_API_KEY."""
    api_key = os.getenv("FORTA_API_KEY", "").strip()
    if not api_key:
        return _skipped("forta", "FORTA_API_KEY not set in MCP server env")

    base = os.getenv("FORTA_API_URL", "https://api.forta.network").rstrip("/")
    headers = {"Authorization": api_key, "Accept": "application/json"}
    findings: list[dict[str, Any]] = []
    try:
        if address:
            url = f"{base}/alerts?addresses={address.strip().lower()}"
            data = _http_get(url, headers=headers)
        elif tx_hash:
            url = f"{base}/alerts?hashes={tx_hash.strip().lower()}"
            data = _http_get(url, headers=headers)
        else:
            return {"success": False, "error": "provide address or tx_hash", "source": "forta"}

        alerts = data if isinstance(data, list) else data.get("alerts") or data.get("results") or []
        for a in alerts[:50]:
            findings.append(
                _finding(
                    source="forta",
                    category=a.get("category") or "forta-alert",
                    severity=str(a.get("severity") or "medium").lower(),
                    description=a.get("description") or a.get("name") or "Forta alert",
                    finding_id=a.get("hash") or a.get("id"),
                    links=[a["link"]] if a.get("link") else [],
                    raw=a,
                )
            )
        return {
            "success": True,
            "source": "forta",
            "findings": findings,
            "finding_count": len(findings),
            "chain": chain,
            "raw_count": len(alerts),
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "forta", "error": str(exc), "findings": []}


def forta_stream_threats(address: str, chain: str = "mainnet") -> dict[str, Any]:
    """Snapshot of recent Forta threats for address (poll, not live stream)."""
    result = forta_get_alerts(address=address, chain=chain)
    if result.get("skipped"):
        return result
    threats = [f for f in result.get("findings", []) if f.get("severity") in ("high", "critical")]
    return {
        **result,
        "threats": threats,
        "threat_count": len(threats),
        "mode": "snapshot",
        "_note": "Live streaming requires Forta webhook integration outside MCP",
    }


def scamsniffer_tx_risk(tx_data: str, chain: str = "mainnet") -> dict[str, Any]:
    """ScamSniffer API — requires SCAMSNIFFER_API_KEY."""
    key = os.getenv("SCAMSNIFFER_API_KEY", "").strip()
    if not key:
        return _skipped("scamsniffer", "SCAMSNIFFER_API_KEY not set in MCP server env")
    base = os.getenv("SCAMSNIFFER_API_URL", "https://api.scamsniffer.io").rstrip("/")
    try:
        data = _http_post(
            f"{base}/v1/tx/check",
            {"chain": chain, "tx_data": tx_data},
            headers={"Authorization": f"Bearer {key}"},
        )
        findings = []
        for item in data.get("risks") or data.get("findings") or []:
            findings.append(
                _finding(
                    source="scamsniffer",
                    category=item.get("type") or "tx-risk",
                    severity=str(item.get("severity") or "medium").lower(),
                    description=item.get("message") or item.get("description") or "ScamSniffer risk",
                    raw=item,
                )
            )
        return {"success": True, "source": "scamsniffer", "findings": findings, "finding_count": len(findings), "raw": data}
    except requests.RequestException as exc:
        return {"success": False, "source": "scamsniffer", "error": str(exc), "findings": []}


def pocket_universe_simulate(tx_data: str, chain: str = "mainnet") -> dict[str, Any]:
    """Pocket Universe simulation API — requires POCKET_UNIVERSE_API_KEY."""
    key = os.getenv("POCKET_UNIVERSE_API_KEY", "").strip()
    if not key:
        return _skipped("pocket_universe", "POCKET_UNIVERSE_API_KEY not set in MCP server env")
    base = os.getenv("POCKET_UNIVERSE_API_URL", "https://api.pocketuniverse.app").rstrip("/")
    try:
        data = _http_post(
            f"{base}/v1/simulate",
            {"chain": chain, "transaction": tx_data},
            headers={"X-API-Key": key},
        )
        findings = []
        if data.get("warning") or data.get("is_dangerous"):
            findings.append(
                _finding(
                    source="pocket_universe",
                    category="simulation-warning",
                    severity="high",
                    description=data.get("warning") or data.get("message") or "Pocket Universe flagged transaction",
                    raw=data,
                )
            )
        return {
            "success": True,
            "source": "pocket_universe",
            "simulation": data,
            "findings": findings,
            "finding_count": len(findings),
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "pocket_universe", "error": str(exc), "findings": []}


def kerberus_url_or_tx_risk(input_value: str, chain: str = "mainnet") -> dict[str, Any]:
    """Kerberus risk check — requires KERBERUS_API_KEY."""
    key = os.getenv("KERBERUS_API_KEY", "").strip()
    if not key:
        return _skipped("kerberus", "KERBERUS_API_KEY not set in MCP server env")
    base = os.getenv("KERBERUS_API_URL", "https://api.kerberus.com").rstrip("/")
    is_url = input_value.startswith("http://") or input_value.startswith("https://")
    path = "/v1/url/check" if is_url else "/v1/tx/check"
    payload = {"url": input_value} if is_url else {"chain": chain, "data": input_value}
    try:
        data = _http_post(f"{base}{path}", payload, headers={"Authorization": f"Bearer {key}"})
        findings = []
        for item in data.get("risks") or []:
            findings.append(
                _finding(
                    source="kerberus",
                    category=item.get("category") or "kerberus-risk",
                    severity=str(item.get("severity") or "medium").lower(),
                    description=item.get("description") or "Kerberus risk",
                    raw=item,
                )
            )
        return {"success": True, "source": "kerberus", "findings": findings, "finding_count": len(findings), "raw": data}
    except requests.RequestException as exc:
        return {"success": False, "source": "kerberus", "error": str(exc), "findings": []}


def web3_antivirus_scan(*, address: str | None = None, source: str | None = None, chain: str = "mainnet") -> dict[str, Any]:
    """Web3 Antivirus API — requires WEB3_ANTIVIRUS_API_KEY."""
    key = os.getenv("WEB3_ANTIVIRUS_API_KEY", "").strip()
    if not key:
        return _skipped("web3_antivirus", "WEB3_ANTIVIRUS_API_KEY not set in MCP server env")
    base = os.getenv("WEB3_ANTIVIRUS_API_URL", "https://api.web3antivirus.io").rstrip("/")
    if address:
        url = f"{base}/v1/scan/address?chain={quote(chain)}&address={address.lower()}"
    elif source:
        return _skipped("web3_antivirus", "source scan requires WEB3_ANTIVIRUS_UPLOAD endpoint — use address scan")
    else:
        return {"success": False, "error": "provide address or source", "source": "web3_antivirus"}
    try:
        data = _http_get(url, headers={"X-API-Key": key})
        findings = []
        for item in data.get("findings") or data.get("issues") or []:
            findings.append(
                _finding(
                    source="web3_antivirus",
                    category=item.get("type") or "ml-risk",
                    severity=str(item.get("severity") or "medium").lower(),
                    description=item.get("description") or item.get("title") or "Web3 Antivirus finding",
                    raw=item,
                )
            )
        return {
            "success": True,
            "source": "web3_antivirus",
            "findings": findings,
            "finding_count": len(findings),
            "risk_chart": data.get("risk_chart") or data.get("score"),
            "raw": data,
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "web3_antivirus", "error": str(exc), "findings": []}


def revoke_list_approvals(address: str, chain: str = "mainnet") -> dict[str, Any]:
    """Read-only approval surface — Revoke.cash deep link + GoPlus allowance hints if available."""
    addr = address.strip().lower()
    if not _ADDR_RE.match(addr):
        return {"success": False, "error": "invalid address", "source": "revoke_cash"}

    revoke_url = f"https://revoke.cash/address/{addr}?chainId={GOPLUS_CHAIN_IDS.get(chain.lower(), '1')}"
    findings = [
        _finding(
            source="revoke_cash",
            category="manual-review",
            severity="info",
            description="Review token approvals via Revoke.cash UI — MCP does not execute revokes",
            links=[revoke_url],
        )
    ]
    goplus = goplus_contract_risk(addr, chain=chain)
    if goplus.get("success") and goplus.get("findings"):
        findings.extend(goplus["findings"])

    return {
        "success": True,
        "source": "revoke_cash",
        "address": addr,
        "chain": chain,
        "revoke_url": revoke_url,
        "findings": findings,
        "finding_count": len(findings),
        "read_only": True,
        "_note": "Revoke actions must be performed by user in wallet/GUI",
    }


def tenderly_simulate(tx: dict[str, Any], chain: str = "mainnet") -> dict[str, Any]:
    """Tenderly transaction simulation — requires TENDERLY_ACCESS_KEY + account/project."""
    access_key = os.getenv("TENDERLY_ACCESS_KEY", "").strip()
    account = os.getenv("TENDERLY_ACCOUNT", "").strip()
    project = os.getenv("TENDERLY_PROJECT", "").strip()
    if not all([access_key, account, project]):
        return _skipped(
            "tenderly",
            "TENDERLY_ACCESS_KEY, TENDERLY_ACCOUNT, TENDERLY_PROJECT required in MCP env",
        )
    url = f"https://api.tenderly.co/api/v1/account/{account}/project/{project}/simulate"
    payload = {"network_id": GOPLUS_CHAIN_IDS.get(chain.lower(), "1"), "transaction": tx}
    try:
        data = _http_post(url, payload, headers={"X-Access-Key": access_key})
        findings = []
        if data.get("transaction", {}).get("status") is False:
            findings.append(
                _finding(
                    source="tenderly",
                    category="simulation-revert",
                    severity="info",
                    description="Transaction would revert in simulation",
                    raw=data.get("transaction"),
                )
            )
        return {
            "success": True,
            "source": "tenderly",
            "simulation": data,
            "findings": findings,
            "finding_count": len(findings),
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "tenderly", "error": str(exc), "findings": []}


def mythx_deep_scan(source_or_path: str, *, chain: str = "mainnet") -> dict[str, Any]:
    """MythX cloud deep scan — requires MYTHX_API_KEY."""
    api_key = os.getenv("MYTHX_API_KEY", "").strip()
    if not api_key:
        return _skipped("mythx", "MYTHX_API_KEY not set — use local mythril_scan_summary as fallback")

    from pathlib import Path

    path = Path(source_or_path)
    if not path.is_file():
        return {"success": False, "error": "mythx_deep_scan requires a file path", "source": "mythx"}

    try:
        import time

        base = "https://api.mythx.io/v1"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        content = path.read_text(encoding="utf-8", errors="replace")
        submit = _http_post(
            f"{base}/analysis",
            {
                "clientToolsVersion": "hexstrike-mcp",
                "contractName": path.stem,
                "sourceMap": content,
                "sourceList": [content],
                "mainSource": content,
            },
            headers=headers,
            timeout=60.0,
        )
        job_id = submit.get("uuid") or submit.get("id")
        if not job_id:
            return {"success": False, "source": "mythx", "error": "no job id", "raw": submit}

        issues_data: dict[str, Any] = {}
        for _ in range(30):
            time.sleep(2)
            issues_data = _http_get(f"{base}/analysis/{job_id}/issues", headers=headers)
            if issues_data.get("issues") is not None:
                break

        findings = []
        for item in issues_data.get("issues") or []:
            findings.append(
                _finding(
                    source="mythx",
                    category=item.get("swcTitle") or item.get("title") or "mythx-issue",
                    severity=str(item.get("severity") or "medium").lower(),
                    description=item.get("description") or "",
                    finding_id=item.get("swcId"),
                    raw=item,
                )
            )
        return {
            "success": True,
            "source": "mythx",
            "job_id": job_id,
            "findings": findings,
            "finding_count": len(findings),
            "chain": chain,
        }
    except requests.RequestException as exc:
        return {"success": False, "source": "mythx", "error": str(exc), "findings": []}


def audit_reports_fetch(*, project: str | None = None, address: str | None = None) -> dict[str, Any]:
    """Fetch public audit report metadata — CERTIK/DeFiLlama style when API keys set."""
    key = os.getenv("AUDIT_REPORTS_API_KEY", "").strip()
    if not key:
        return {
            "success": True,
            "skipped": True,
            "skip_reason": "AUDIT_REPORTS_API_KEY not set — manual search: https://de.fi/scanner, Certik Skynet",
            "source": "audit_reports",
            "reports": [],
            "search_hints": [
                f"https://skynet.certik.com/projects/{project}" if project else None,
                f"https://de.fi/scanner/contract/{address}" if address else None,
            ],
            "findings": [],
        }
    base = os.getenv("AUDIT_REPORTS_API_URL", "https://api.certik.io").rstrip("/")
    try:
        q = project or address or ""
        data = _http_get(f"{base}/v1/audits/search?q={quote(q)}", headers={"Authorization": f"Bearer {key}"})
        reports = data.get("reports") or data.get("data") or []
        return {"success": True, "source": "audit_reports", "reports": reports, "report_count": len(reports), "findings": []}
    except requests.RequestException as exc:
        return {"success": False, "source": "audit_reports", "error": str(exc), "reports": []}


def chainstack_rpc_call(chain: str, method: str, params: list[Any] | None = None) -> dict[str, Any]:
    """Generic JSON-RPC via CHAINSTACK_RPC_URL or WEB3_RPC_URL."""
    from hexstrike.mcp.web3_rpc_runner import _rpc_call, resolve_rpc_endpoint

    suffix = chain.upper().replace("-", "_")
    url = os.getenv(f"CHAINSTACK_RPC_URL_{suffix}") or os.getenv("CHAINSTACK_RPC_URL")
    if url:
        ep = {"success": True, "_url": url.rstrip("/"), "rpc_url_redacted": url.split("?")[0]}
    else:
        ep = resolve_rpc_endpoint(chain)
    if not ep.get("success"):
        return ep
    try:
        resp = _rpc_call(ep["_url"], method, params or [])
        return {
            "success": resp.get("success", True),
            "source": "chainstack_rpc",
            "chain": chain,
            "method": method,
            "result": resp.get("result"),
            "error": resp.get("error"),
            "read_only": True,
        }
    except Exception as exc:
        return {"success": False, "source": "chainstack_rpc", "error": str(exc)}


def chainstack_indexer_query(chain: str, query: str) -> dict[str, Any]:
    """Chainstack indexer GraphQL/SQL — requires CHAINSTACK_INDEXER_URL."""
    url = os.getenv("CHAINSTACK_INDEXER_URL", "").strip()
    if not url:
        return _skipped("chainstack_indexer", "CHAINSTACK_INDEXER_URL not set")
    try:
        data = _http_post(url, {"query": query, "chain": chain})
        return {"success": True, "source": "chainstack_indexer", "data": data, "read_only": True}
    except requests.RequestException as exc:
        return {"success": False, "source": "chainstack_indexer", "error": str(exc)}


def docs_search(term: str) -> dict[str, Any]:
    """Search local HexStrike Web3 audit docs (read-only)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    search_dirs = [
        root / ".cursor/skills",
        root / "config/mcp",
        root / "config/skills/schemas",
    ]
    hits: list[dict[str, str]] = []
    term_l = term.lower()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for path in d.rglob("*"):
            if path.suffix not in (".md", ".json") or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if term_l in text.lower():
                hits.append({"file": str(path.relative_to(root)), "snippet": text[:300]})
            if len(hits) >= 20:
                break
    return {"success": True, "source": "docs_search", "term": term, "hits": hits, "hit_count": len(hits)}


def alchemy_get_nft_metadata(address: str, token_id: str, chain: str = "mainnet") -> dict[str, Any]:
    """Alchemy NFT metadata API — requires ALCHEMY_API_KEY."""
    key = os.getenv("ALCHEMY_API_KEY", "").strip()
    if not key:
        return _skipped("alchemy", "ALCHEMY_API_KEY not set in MCP server env")
    network = {"mainnet": "eth-mainnet", "polygon": "polygon-mainnet", "base": "base-mainnet"}.get(chain.lower(), "eth-mainnet")
    url = f"https://{network}.g.alchemy.com/nft/v3/{key}/getNFTMetadata?contractAddress={address}&tokenId={token_id}"
    try:
        data = _http_get(url)
        return {"success": True, "source": "alchemy", "metadata": data, "findings": [], "read_only": True}
    except requests.RequestException as exc:
        return {"success": False, "source": "alchemy", "error": str(exc)}


def infura_get_logs(
    address: str,
    topics: list[str] | None = None,
    from_block: str = "latest",
    to_block: str = "latest",
    chain: str = "mainnet",
) -> dict[str, Any]:
    """eth_getLogs via Infura/WEB3 RPC env."""
    from hexstrike.mcp.web3_rpc_runner import rpc_event_intel

    topic = topics[0] if topics else None
    return rpc_event_intel(address, chain=chain, topic=topic, from_block=from_block, to_block=to_block)
