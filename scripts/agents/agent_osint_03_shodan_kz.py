#!/usr/bin/env python3
"""Agent-OSINT-03: Shodan + passive OSINT scan for Kazakhstan infra targets.

Read-only / defensive IR — discovers exposed Geth :8545, Jenkins, crypto RPC.
Uses Shodan API when SHODAN_API_KEY is set; falls back to RIPEstat + crt.sh + InternetDB.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from crypto_rpc_orchestrator import probe_node, score_node  # noqa: E402

DEFAULT_OUT = ROOT / "artifacts" / "shodan-kz-report.json"

# Defensive Shodan dorks — crypto signing / drainer-adjacent infra in KZ
SHODAN_QUERIES = [
    'country:"KZ" port:8545',
    'country:"KZ" "Geth"',
    'country:"KZ" port:8545 "personal"',
    'country:"KZ" port:8545 ethereum',
    'country:"KZ" jenkins port:8080',
    'country:"KZ" port:8545 "txpool"',
    'country:"KZ" org:"PS Internet"',
    'country:"KZ" org:"Kar-Tel"',
]

# Known KZ hosting / telecom ASNs (seed for RIPEstat fallback)
KZ_ASN_SEEDS = [
    "AS9198",   # KazTransCom/JSC
    "AS48503",  # Kar-Tel / Beeline KZ
    "AS21299",  # PS Internet (hosting)
    "AS35104",  # Kazakhtelecom
    "AS207704", # Hosters.kz / local hosting
    "AS200590", # Cloud KZ providers
]


def http_json(url: str, timeout: float = 12.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HexStrike-OSINT/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def shodan_search(api_key: str, query: str, limit: int = 50) -> dict[str, Any]:
    params = urllib.parse.urlencode({"key": api_key, "query": query, "minify": "true"})
    url = f"https://api.shodan.io/shodan/host/search?{params}"
    try:
        data = http_json(url)
        matches = data.get("matches") or []
        return {
            "query": query,
            "total": data.get("total", 0),
            "matches": matches[:limit],
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        return {"query": query, "total": 0, "matches": [], "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:  # noqa: BLE001
        return {"query": query, "total": 0, "matches": [], "error": str(exc)}


def shodan_host(api_key: str, ip: str) -> dict[str, Any]:
    url = f"https://api.shodan.io/shodan/host/{ip}?key={urllib.parse.quote(api_key)}"
    try:
        return http_json(url)
    except Exception as exc:  # noqa: BLE001
        return {"ip": ip, "error": str(exc)}


def internetdb(ip: str) -> dict[str, Any]:
    try:
        return http_json(f"https://internetdb.shodan.io/{ip}", timeout=8.0)
    except Exception as exc:  # noqa: BLE001
        return {"ip": ip, "error": str(exc)}


def ripe_kz_asns() -> list[str]:
    try:
        data = http_json("https://stat.ripe.net/data/country-resource-list/data.json?resource=KZ")
        asns = data.get("data", {}).get("resources", {}).get("asn", []) or []
        return [f"AS{a}" if not str(a).upper().startswith("AS") else str(a).upper() for a in asns[:30]]
    except Exception:
        return KZ_ASN_SEEDS


def ripe_announced_ips(asn: str, max_ips: int = 5) -> list[str]:
    """Sample a few IPs from announced prefixes (passive BGP data, no port scan)."""
    ips: list[str] = []
    try:
        asn_num = asn.upper().replace("AS", "")
        data = http_json(
            f"https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS{asn_num}",
            timeout=10,
        )
        prefixes = data.get("data", {}).get("prefixes", []) or []
        for entry in prefixes[:8]:
            prefix = entry.get("prefix", "")
            if not prefix or "/" not in prefix:
                continue
            base_ip = prefix.split("/")[0]
            # Use network address as candidate for InternetDB enrichment only
            if base_ip not in ips:
                ips.append(base_ip)
            if len(ips) >= max_ips:
                break
    except Exception:
        pass
    return ips


def crtsh_kz_domains(limit: int = 40) -> list[str]:
    domains: list[str] = []
    try:
        url = "https://crt.sh/?q=%.kz&output=json"
        req = urllib.request.Request(url, headers={"User-Agent": "HexStrike-OSINT/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = json.loads(resp.read().decode())
        seen: set[str] = set()
        for row in rows:
            for field in ("common_name", "name_value"):
                val = row.get(field) or ""
                for part in val.split("\n"):
                    d = part.strip().lower().lstrip("*.")
                    if d.endswith(".kz") and d not in seen and " " not in d:
                        seen.add(d)
                        domains.append(d)
                        if len(domains) >= limit:
                            return domains
    except Exception:
        pass
    return domains


def resolve_a(domain: str) -> list[str]:
    try:
        out = subprocess.check_output(["host", "-t", "A", domain], text=True, timeout=8, stderr=subprocess.DEVNULL)
        ips = re.findall(r"has address (\d+\.\d+\.\d+\.\d+)", out)
        return list(dict.fromkeys(ips))
    except Exception:
        try:
            return list({addr[4][0] for addr in socket.getaddrinfo(domain, None, socket.AF_INET)})
        except Exception:
            return []


def ipinfo(ip: str) -> dict[str, Any]:
    try:
        return http_json(f"https://ipinfo.io/{ip}/json", timeout=8.0)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def extract_shodan_ips(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    targets: list[dict[str, Any]] = []
    for block in results:
        for m in block.get("matches") or []:
            ip = m.get("ip_str") or m.get("ip")
            if not ip or ip in seen:
                continue
            seen.add(ip)
            targets.append({
                "ip": ip,
                "ports": m.get("ports") or [],
                "org": m.get("org"),
                "hostnames": m.get("hostnames") or [],
                "product": m.get("product"),
                "vulns": list((m.get("vulns") or {}).keys()) if isinstance(m.get("vulns"), dict) else (m.get("vulns") or []),
                "tags": m.get("tags") or [],
                "source": "shodan_search",
                "query": block.get("query"),
            })
    return targets


def classify_risk(target: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    ports = set(target.get("ports") or [])
    if 8545 in ports:
        flags.append("ETH_RPC_8545")
    if 8080 in ports:
        flags.append("JENKINS_8080")
    if 22 in ports:
        flags.append("SSH_22")
    vulns = target.get("vulns") or []
    if vulns:
        flags.append(f"CVE_COUNT_{len(vulns)}")
    probe = target.get("geth_probe") or {}
    for f in probe.get("risk_flags") or []:
        flags.append(f)
    if any("PERSONAL" in f or "CRITICAL" in f for f in flags):
        flags.append("HIGH_RISK_SIGNING_EXPOSURE")
    return flags


def probe_geth_targets(targets: list[dict[str, Any]], timeout: float = 6.0) -> None:
    for t in targets:
        ports = set(t.get("ports") or [])
        if 8545 not in ports and "ETH_RPC_8545" not in t.get("risk_flags", []):
            continue
        node = {
            "ip": t["ip"],
            "org": t.get("org") or "unknown",
            "country": t.get("country") or "KZ",
        }
        result = probe_node(node, port=8545, timeout=timeout)
        t["geth_probe"] = {
            "reachable": result.reachable,
            "client_version": result.client_version,
            "chain_id": result.chain_id,
            "risk_flags": result.risk_flags,
            "rpc_modules": result.rpc_modules,
            "score": score_node(result),
        }


def main() -> int:
    out_path = Path(os.environ.get("OUTPUT", str(DEFAULT_OUT)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("SHODAN_API_KEY", "").strip()

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": "Agent-OSINT-03",
        "task": "shodan-kz-scan",
        "mode": "read-only_passive",
        "country": "KZ",
        "shodan_api": bool(api_key),
        "queries": SHODAN_QUERIES,
        "targets": [],
        "high_risk": [],
        "notes": [],
    }

    candidate_ips: dict[str, dict[str, Any]] = {}

    # --- Phase A: Shodan API search ---
    shodan_blocks: list[dict[str, Any]] = []
    if api_key:
        for q in SHODAN_QUERIES:
            block = shodan_search(api_key, q)
            shodan_blocks.append(block)
            report["notes"].append(f"Shodan '{q}': total={block.get('total')} err={block.get('error')}")
        for t in extract_shodan_ips(shodan_blocks):
            candidate_ips[t["ip"]] = t
    else:
        report["notes"].append(
            "SHODAN_API_KEY not set — using RIPEstat + crt.sh + InternetDB fallback. "
            "Set key in .env for full Shodan search."
        )

    # --- Phase B: RIPEstat KZ ASNs → InternetDB ---
    asns = ripe_kz_asns()
    report["kz_asns_sampled"] = asns[:15]
    for asn in (KZ_ASN_SEEDS + asns)[:12]:
        for ip in ripe_announced_ips(asn, max_ips=3):
            if ip in candidate_ips:
                continue
            idb = internetdb(ip)
            geo = ipinfo(ip)
            if geo.get("country") not in (None, "KZ", "RU", "KG", "UZ"):
                continue
            entry = {
                "ip": ip,
                "ports": idb.get("ports") or [],
                "org": geo.get("org"),
                "country": geo.get("country"),
                "hostnames": idb.get("hostnames") or [],
                "vulns": idb.get("vulns") or [],
                "tags": idb.get("tags") or [],
                "source": "ripe_internetdb",
                "asn": asn,
            }
            candidate_ips[ip] = entry

    # --- Phase C: .kz domains → resolve → InternetDB ---
    domains = crtsh_kz_domains(limit=25)
    report["kz_domains_sampled"] = len(domains)
    for domain in domains[:20]:
        for ip in resolve_a(domain):
            if ip in candidate_ips:
                candidate_ips[ip].setdefault("domains", []).append(domain)
                continue
            idb = internetdb(ip)
            geo = ipinfo(ip)
            candidate_ips[ip] = {
                "ip": ip,
                "ports": idb.get("ports") or [],
                "org": geo.get("org"),
                "country": geo.get("country"),
                "hostnames": list(set((idb.get("hostnames") or []) + [domain])),
                "vulns": idb.get("vulns") or [],
                "tags": idb.get("tags") or [],
                "source": "crtsh_resolve",
                "domains": [domain],
            }

    targets = list(candidate_ips.values())
    for t in targets:
        t["risk_flags"] = classify_risk(t)

    # Read-only Geth probe on :8545 candidates
    probe_geth_targets(targets)

    # Re-classify after probe
    for t in targets:
        t["risk_flags"] = classify_risk(t)
        t["risk_score"] = len(t["risk_flags"]) + (t.get("geth_probe") or {}).get("score", 0)

    targets.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    report["targets"] = targets
    report["total_candidates"] = len(targets)
    report["geth_8545_candidates"] = sum(
        1 for t in targets if 8545 in (t.get("ports") or []) or (t.get("geth_probe") or {}).get("reachable")
    )
    report["high_risk"] = [
        {
            "ip": t["ip"],
            "ports": t.get("ports"),
            "risk_flags": t.get("risk_flags"),
            "org": t.get("org"),
            "source": t.get("source"),
            "geth_probe": t.get("geth_probe"),
        }
        for t in targets
        if any(
            f in (t.get("risk_flags") or [])
            for f in ("HIGH_RISK_SIGNING_EXPOSURE", "ETH_RPC_8545", "JENKINS_8080")
        )
        or (t.get("geth_probe") or {}).get("score", 0) >= 3
    ][:30]

    if api_key:
        report["shodan_query_results"] = [
            {"query": b["query"], "total": b.get("total"), "error": b.get("error"), "returned": len(b.get("matches") or [])}
            for b in shodan_blocks
        ]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "success": True,
        "output": str(out_path),
        "total_candidates": report["total_candidates"],
        "high_risk_count": len(report["high_risk"]),
        "geth_8545": report["geth_8545_candidates"],
        "shodan_api": report["shodan_api"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
