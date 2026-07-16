"""Production Shodan OSINT collector for Samson recon agent.

Fires real async HTTP requests against api.shodan.io, enforces PostgreSQL-backed
ApiCreditBudget + 1-query/5s rate limit, persists ShodanReconArtifact, and writes
CVE summaries into the RAG docs tree for infrastructural risk retrieval.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from samson.core.config import SamsonSettings, get_settings, repo_root
from samson.core.database import AuditRepository, Database, sha256_payload
from samson.core.errors import ConfigurationError, NetworkError
from samson.redteam.schemas import (
    ApiCreditBudget,
    ShodanCollectResult,
    ShodanReconArtifact,
    ShodanServiceBanner,
)

logger = logging.getLogger(__name__)

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_IP_RE = re.compile(
    r"^(?:"
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)"
    r"|"
    r"[0-9a-fA-F:]+"
    r")$"
)


class SamsonShodanClient:
    """Async Shodan host intelligence client with credit budget and hard rate limiting."""

    def __init__(
        self,
        settings: SamsonSettings | None = None,
        *,
        api_key: str | None = None,
        database_url: str | None = None,
    ) -> None:
        if database_url:
            settings = SamsonSettings(database_url=database_url)
        self._settings = settings or get_settings()
        self._api_key = (api_key or self._settings.shodan_api_key or "").strip()
        self._base_url = str(self._settings.shodan_api_base_url).rstrip("/")
        self._budget_id = self._settings.shodan_budget_id
        self._db = Database(self._settings)
        self._audit = AuditRepository(self._db)
        self._client: httpx.AsyncClient | None = None
        self._rate_lock = asyncio.Lock()
        self._last_query_monotonic: float | None = None

    async def __aenter__(self) -> SamsonShodanClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def collect_host(
        self,
        ip_address: str,
        *,
        operator_id: str,
        request_id: UUID | None = None,
        run_id: UUID | None = None,
        history: bool = False,
        minify: bool = False,
    ) -> ShodanCollectResult:
        """Lookup a single host on Shodan with budget + rate-limit enforcement."""
        request_id = request_id or uuid4()
        ip = (ip_address or "").strip()
        if not ip or not _IP_RE.match(ip):
            raise ConfigurationError("Invalid IP address for Shodan host lookup", ip=ip_address)

        if not self._api_key:
            raise ConfigurationError(
                "Shodan API key missing — set SAMSON_SHODAN_API_KEY",
                budget_id=self._budget_id,
            )

        budget = await asyncio.to_thread(self._load_or_init_budget)
        if budget.credits_remaining < 1 or budget.is_blocked:
            await self._block_and_audit(
                request_id=request_id,
                operator_id=operator_id,
                run_id=run_id,
                ip_address=ip,
                budget=budget,
                reason="Shodan API credits exhausted (credits_remaining < 1)",
            )
            return ShodanCollectResult(
                request_id=request_id,
                ip_address=ip,
                is_blocked=True,
                block_reason="credits_exhausted",
                credits_remaining=budget.credits_remaining,
            )

        await self._enforce_rate_limit(budget.min_interval_sec)

        url = f"{self._base_url}/shodan/host/{ip}"
        params: dict[str, Any] = {"key": self._api_key}
        if history:
            params["history"] = "true"
        if minify:
            params["minify"] = "true"

        client = await self._ensure_client()
        start = time.perf_counter()
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"Shodan host lookup transport failure for {ip}",
                ip=ip,
                error=str(exc),
            ) from exc

        duration_ms = int((time.perf_counter() - start) * 1000)
        if response.status_code == 401:
            raise ConfigurationError("Shodan API key rejected (401)", ip=ip, status_code=401)
        if response.status_code == 404:
            payload: dict[str, Any] = {"error": "No information available for that IP", "ip": ip}
        elif response.status_code >= 400:
            raise NetworkError(
                f"Shodan host lookup failed HTTP {response.status_code}",
                ip=ip,
                status_code=response.status_code,
                body=response.text[:2000],
            )
        else:
            try:
                parsed = response.json()
            except json.JSONDecodeError as exc:
                raise NetworkError("Shodan returned non-JSON payload", ip=ip) from exc
            if not isinstance(parsed, dict):
                raise NetworkError("Shodan host payload must be a JSON object", ip=ip)
            payload = parsed

        artifact = self._parse_host_payload(
            payload=payload,
            ip_address=ip,
            operator_id=operator_id,
            request_id=request_id,
        )
        rag_path = await asyncio.to_thread(self._write_rag_markdown, artifact)
        artifact = artifact.model_copy(update={"rag_doc_path": str(rag_path)})

        await asyncio.to_thread(self._persist_artifact, artifact, run_id)
        new_budget = await asyncio.to_thread(self._consume_credit, budget)

        if self._settings.audit_enabled:
            await asyncio.to_thread(
                self._audit.write_redteam_audit,
                request_id=request_id,
                tool="shodan_collector",
                operator_id=operator_id,
                action="collect_host",
                outcome="pass",
                payload_hash=sha256_payload(
                    {
                        "ip": ip,
                        "cves": artifact.detected_vulnerabilities,
                        "ports": artifact.open_ports,
                    }
                ),
                duration_ms=duration_ms,
                run_id=run_id,
            )

        logger.info(
            "Shodan recon ip=%s ports=%d cves=%d credits_remaining=%d",
            ip,
            len(artifact.open_ports),
            len(artifact.detected_vulnerabilities),
            new_budget.credits_remaining,
        )
        return ShodanCollectResult(
            request_id=request_id,
            ip_address=ip,
            is_blocked=False,
            credits_remaining=new_budget.credits_remaining,
            artifact=artifact,
            http_status_code=response.status_code,
        )

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.http_timeout_sec),
                headers={"User-Agent": self._settings.http_user_agent},
                follow_redirects=True,
            )
        return self._client

    async def _enforce_rate_limit(self, min_interval_sec: float) -> None:
        """Hard limiter: max 1 Shodan query per min_interval_sec (default 5s)."""
        interval = max(float(min_interval_sec), float(self._settings.shodan_min_interval_sec))
        async with self._rate_lock:
            now = time.monotonic()
            if self._last_query_monotonic is not None:
                elapsed = now - self._last_query_monotonic
                remaining = interval - elapsed
                if remaining > 0:
                    logger.info("Shodan rate-limit sleep %.2fs", remaining)
                    await asyncio.sleep(remaining)
            self._last_query_monotonic = time.monotonic()

    def _load_or_init_budget(self) -> ApiCreditBudget:
        row = self._db.fetchone(
            """
            SELECT budget_id, provider, credits_remaining, credits_total,
                   min_interval_sec, last_query_at, is_blocked, updated_at
            FROM api_credit_budgets
            WHERE budget_id = :budget_id
            """,
            {"budget_id": self._budget_id},
        )
        if not row:
            self._db.execute(
                """
                INSERT INTO api_credit_budgets (
                    budget_id, provider, credits_remaining, credits_total,
                    min_interval_sec, is_blocked
                ) VALUES (
                    :budget_id, 'shodan', :credits, :credits, :min_interval, FALSE
                )
                """,
                {
                    "budget_id": self._budget_id,
                    "credits": int(self._settings.shodan_initial_credits),
                    "min_interval": float(self._settings.shodan_min_interval_sec),
                },
            )
            return ApiCreditBudget(
                budget_id=self._budget_id,
                provider="shodan",
                credits_remaining=int(self._settings.shodan_initial_credits),
                credits_total=int(self._settings.shodan_initial_credits),
                min_interval_sec=float(self._settings.shodan_min_interval_sec),
                is_blocked=False,
            )

        last_query = row.get("last_query_at")
        if isinstance(last_query, str):
            last_query = datetime.fromisoformat(last_query)
        updated = row.get("updated_at")
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)
        if updated is None:
            updated = datetime.now(timezone.utc)

        return ApiCreditBudget(
            budget_id=str(row["budget_id"]),
            provider=str(row["provider"]),
            credits_remaining=int(row["credits_remaining"]),
            credits_total=int(row["credits_total"]),
            min_interval_sec=float(row["min_interval_sec"]),
            last_query_at=last_query,
            is_blocked=bool(row["is_blocked"]),
            updated_at=updated,
        )

    def _consume_credit(self, budget: ApiCreditBudget) -> ApiCreditBudget:
        remaining = max(int(budget.credits_remaining) - 1, 0)
        blocked = remaining < 1
        self._db.execute(
            """
            UPDATE api_credit_budgets
            SET credits_remaining = :credits_remaining,
                last_query_at = NOW(),
                is_blocked = :is_blocked,
                updated_at = NOW()
            WHERE budget_id = :budget_id
            """,
            {
                "budget_id": budget.budget_id,
                "credits_remaining": remaining,
                "is_blocked": blocked,
            },
        )
        return budget.model_copy(
            update={
                "credits_remaining": remaining,
                "is_blocked": blocked,
                "last_query_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )

    async def _block_and_audit(
        self,
        *,
        request_id: UUID,
        operator_id: str,
        run_id: UUID | None,
        ip_address: str,
        budget: ApiCreditBudget,
        reason: str,
    ) -> None:
        logger.critical(
            "Shodan execution blocked: %s budget_id=%s credits_remaining=%s ip=%s",
            reason,
            budget.budget_id,
            budget.credits_remaining,
            ip_address,
        )
        await asyncio.to_thread(
            self._db.execute,
            """
            UPDATE api_credit_budgets
            SET is_blocked = TRUE, updated_at = NOW()
            WHERE budget_id = :budget_id
            """,
            {"budget_id": budget.budget_id},
        )
        if self._settings.audit_enabled:
            await asyncio.to_thread(
                self._audit.write_redteam_audit,
                request_id=request_id,
                tool="shodan_collector",
                operator_id=operator_id,
                action="collect_host_blocked",
                outcome="critical",
                payload_hash=sha256_payload(
                    {
                        "ip": ip_address,
                        "reason": reason,
                        "credits_remaining": budget.credits_remaining,
                    }
                ),
                duration_ms=0,
                run_id=run_id,
            )

    @classmethod
    def _parse_host_payload(
        cls,
        *,
        payload: dict[str, Any],
        ip_address: str,
        operator_id: str,
        request_id: UUID,
    ) -> ShodanReconArtifact:
        open_ports = sorted(
            {
                int(p)
                for p in (payload.get("ports") or [])
                if str(p).isdigit() or isinstance(p, int)
            }
        )
        banners: list[ShodanServiceBanner] = []
        cves: set[str] = set()

        for cve in cls._extract_cves(payload.get("vulns")):
            cves.add(cve)

        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            port = item.get("port")
            if port is None:
                continue
            try:
                port_i = int(port)
            except (TypeError, ValueError):
                continue
            open_ports.append(port_i)
            banner_text = str(item.get("data") or item.get("banner") or "")
            banners.append(
                ShodanServiceBanner(
                    port=port_i,
                    transport=str(item.get("transport") or "tcp"),
                    product=(str(item["product"]) if item.get("product") else None),
                    version=(str(item["version"]) if item.get("version") else None),
                    banner=banner_text[:8000],
                    timestamp=(str(item["timestamp"]) if item.get("timestamp") else None),
                )
            )
            for cve in cls._extract_cves(item.get("vulns")):
                cves.add(cve)
            for cve in _CVE_RE.findall(banner_text):
                cves.add(cve.upper())

        open_ports = sorted(set(open_ports))
        hostnames = [str(h) for h in (payload.get("hostnames") or []) if h]
        return ShodanReconArtifact(
            artifact_id=uuid4(),
            request_id=request_id,
            ip_address=str(payload.get("ip_str") or ip_address),
            operator_id=operator_id,
            hostnames=hostnames,
            org=(str(payload["org"]) if payload.get("org") else None),
            isp=(str(payload["isp"]) if payload.get("isp") else None),
            asn=(str(payload["asn"]) if payload.get("asn") else None),
            os=(str(payload["os"]) if payload.get("os") else None),
            country_code=(str(payload["country_code"]) if payload.get("country_code") else None),
            city=(str(payload["city"]) if payload.get("city") else None),
            open_ports=open_ports,
            banners=banners,
            detected_vulnerabilities=sorted(cves),
            raw_payload=payload,
        )

    @staticmethod
    def _extract_cves(vulns: Any) -> list[str]:
        found: list[str] = []
        if vulns is None:
            return found
        if isinstance(vulns, dict):
            candidates = list(vulns.keys())
        elif isinstance(vulns, list):
            candidates = [str(v) for v in vulns]
        elif isinstance(vulns, str):
            candidates = [vulns]
        else:
            return found
        for item in candidates:
            text = str(item).upper()
            if _CVE_RE.fullmatch(text) or text.startswith("CVE-"):
                found.append(text if text.startswith("CVE-") else text)
            else:
                found.extend(m.upper() for m in _CVE_RE.findall(text))
        return sorted(set(found))

    def _write_rag_markdown(self, artifact: ShodanReconArtifact) -> Path:
        out_dir = self._settings.rag_docs_path / "emulation"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"shodan_{artifact.ip_address.replace(':', '_')}_{artifact.artifact_id}.md"
        cve_lines = [f"- `{cve}`" for cve in artifact.detected_vulnerabilities] or ["_None detected_"]
        port_lines = [f"- `{p}`" for p in artifact.open_ports] or ["_None_"]
        banner_lines: list[str] = []
        for banner in artifact.banners[:32]:
            excerpt = banner.banner.replace("```", "'''")[:500]
            banner_lines.append(
                f"### Port {banner.port}/{banner.transport}\n"
                f"- product: `{banner.product or 'n/a'}`\n"
                f"- version: `{banner.version or 'n/a'}`\n"
                f"```\n{excerpt}\n```"
            )
        if not banner_lines:
            banner_lines = ["_No banners_"]

        path.write_text(
            "\n".join(
                [
                    f"# Shodan Recon Artifact `{artifact.artifact_id}`",
                    "",
                    f"- **IP:** `{artifact.ip_address}`",
                    f"- **Operator:** `{artifact.operator_id}`",
                    f"- **Org / ISP:** `{artifact.org or 'n/a'}` / `{artifact.isp or 'n/a'}`",
                    f"- **ASN:** `{artifact.asn or 'n/a'}`",
                    f"- **OS:** `{artifact.os or 'n/a'}`",
                    f"- **Geo:** `{artifact.city or 'n/a'}`, `{artifact.country_code or 'n/a'}`",
                    f"- **Hostnames:** {', '.join(f'`{h}`' for h in artifact.hostnames) or '_none_'}",
                    f"- **Collected at:** `{artifact.collected_at.isoformat()}`",
                    "",
                    "## Open ports",
                    *port_lines,
                    "",
                    "## Detected vulnerabilities (CVEs)",
                    *cve_lines,
                    "",
                    "## Service banners",
                    *banner_lines,
                    "",
                    "## Infrastructural risk summary",
                    (
                        f"Host `{artifact.ip_address}` exposes {len(artifact.open_ports)} open ports "
                        f"and {len(artifact.detected_vulnerabilities)} CVE identifiers indexed by Shodan. "
                        "Use this context during authorized purple-team impact simulation and guardrail design."
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        # Keep repo-relative path stable for RAG loaders regardless of CWD.
        try:
            return path.relative_to(repo_root())
        except ValueError:
            return path

    def _persist_artifact(self, artifact: ShodanReconArtifact, run_id: UUID | None) -> None:
        self._db.execute(
            """
            INSERT INTO shodan_recon_artifacts (
                artifact_id, request_id, run_id, operator_id, ip_address, hostnames,
                org, isp, asn, os, country_code, city, open_ports, banners,
                detected_vulnerabilities, raw_payload, rag_doc_path, collected_at
            ) VALUES (
                :artifact_id, :request_id, :run_id, :operator_id, :ip_address, :hostnames,
                :org, :isp, :asn, :os, :country_code, :city, :open_ports,
                CAST(:banners AS jsonb), :detected_vulnerabilities,
                CAST(:raw_payload AS jsonb), :rag_doc_path, :collected_at
            )
            ON CONFLICT (artifact_id) DO UPDATE SET
                open_ports = EXCLUDED.open_ports,
                banners = EXCLUDED.banners,
                detected_vulnerabilities = EXCLUDED.detected_vulnerabilities,
                raw_payload = EXCLUDED.raw_payload,
                rag_doc_path = EXCLUDED.rag_doc_path
            """,
            {
                "artifact_id": str(artifact.artifact_id),
                "request_id": str(artifact.request_id),
                "run_id": str(run_id) if run_id else None,
                "operator_id": artifact.operator_id,
                "ip_address": artifact.ip_address,
                "hostnames": artifact.hostnames,
                "org": artifact.org,
                "isp": artifact.isp,
                "asn": artifact.asn,
                "os": artifact.os,
                "country_code": artifact.country_code,
                "city": artifact.city,
                "open_ports": artifact.open_ports,
                "banners": json.dumps([b.model_dump(mode="json") for b in artifact.banners]),
                "detected_vulnerabilities": artifact.detected_vulnerabilities,
                "raw_payload": json.dumps(artifact.raw_payload),
                "rag_doc_path": artifact.rag_doc_path,
                "collected_at": artifact.collected_at.isoformat(),
            },
        )
