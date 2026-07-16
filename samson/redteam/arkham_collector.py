"""Arkham Intelligence on-chain OSINT collector for Samson SBM.

Read-only address attribution via ``https://api.arkm.com`` (API-Key header).
Cache-first Postgres persistence + RAG markdown under ``samson/rag/docs/emulation/``.
Never hardcodes API keys — use ``SAMSON_ARKHAM_API_KEY`` / ``ARKHAM_API_KEY``.
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

from samson.core.config import SamsonSettings, get_settings
from samson.core.database import AuditRepository, Database, sha256_payload
from samson.core.errors import ConfigurationError, NetworkError
from samson.core.http_client import OllamaClient
from samson.core.scope import ScopeEnforcer
from samson.rag.search.ingest import DocumentIngester
from samson.redteam.schemas import (
    ArkhamAddressArtifact,
    ArkhamChainIntelligence,
    ArkhamCollectResult,
    ArkhamEntityRef,
)

logger = logging.getLogger(__name__)

_EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SamsonArkhamClient:
    """Async Arkham Intel client with local cache and rate pacing."""

    def __init__(
        self,
        settings: SamsonSettings | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._api_key = (api_key or self._settings.arkham_api_key or "").strip()
        self._base_url = str(self._settings.arkham_api_base_url).rstrip("/")
        self._db = Database(self._settings)
        self._audit = AuditRepository(self._db)
        self._scope = ScopeEnforcer(self._settings)
        self._ollama = OllamaClient(self._settings)
        self._ingester = DocumentIngester(self._settings, self._db, self._ollama)
        self._client: httpx.AsyncClient | None = None
        self._rate_lock = asyncio.Lock()
        self._last_query_monotonic: float | None = None

    async def __aenter__(self) -> SamsonArkhamClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._ingester.close()
        self._ollama.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=_HTTP_TIMEOUT,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def _pace(self) -> None:
        interval = float(self._settings.arkham_min_interval_sec)
        async with self._rate_lock:
            now = time.monotonic()
            if self._last_query_monotonic is not None:
                wait = interval - (now - self._last_query_monotonic)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_query_monotonic = time.monotonic()

    async def lookup_address(
        self,
        address: str,
        *,
        operator_id: str = "operator-alpha",
        request_id: UUID | None = None,
        run_id: UUID | None = None,
        chain: str | None = None,
        force_refresh: bool = False,
        all_chains: bool = True,
    ) -> ArkhamCollectResult:
        """Cache-first Arkham address intelligence (entity / label attribution)."""
        request_id = request_id or uuid4()
        addr = (address or "").strip()
        if not _EVM_ADDRESS_RE.match(addr):
            raise ConfigurationError(
                "Invalid EVM address for Arkham lookup",
                address=address,
            )
        self._scope.assert_operator(operator_id, request_id=request_id)

        if not force_refresh:
            cached = await asyncio.to_thread(self.get_cached_artifact, addr)
            if cached is not None:
                logger.info("[+] Arkham cache hit for %s — 0 API credits", addr)
                if self._settings.audit_enabled:
                    await asyncio.to_thread(
                        self._audit.write_redteam_audit,
                        request_id=request_id,
                        tool="arkham_collector",
                        operator_id=operator_id,
                        action="lookup_address_cache",
                        outcome="pass",
                        payload_hash=sha256_payload({"address": addr, "from_cache": True}),
                        duration_ms=0,
                        run_id=run_id,
                    )
                return ArkhamCollectResult(
                    request_id=request_id,
                    address=addr,
                    from_cache=True,
                    http_status_code=200,
                    artifact=cached,
                )

        if not self._api_key:
            raise ConfigurationError(
                "Arkham API key missing — set SAMSON_ARKHAM_API_KEY",
            )

        await self._pace()
        client = await self._ensure_client()
        started = time.perf_counter()
        headers = {"API-Key": self._api_key}

        if all_chains and not chain:
            path = f"/intelligence/address/{addr}/all"
            params: dict[str, Any] | None = None
        else:
            path = f"/intelligence/address/{addr}"
            params = {"chain": chain} if chain else None

        # Suppress httpx URL dumps — headers carry the API key; body is fine.
        httpx_log = logging.getLogger("httpx")
        prev = httpx_log.level
        try:
            httpx_log.setLevel(logging.WARNING)
            logger.info("Arkham GET %s%s (api_key=REDACTED)", self._base_url, path)
            response = await client.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"Arkham transport failure for {addr}",
                address=addr,
                error=str(exc),
            ) from exc
        finally:
            httpx_log.setLevel(prev)

        duration_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 401:
            raise ConfigurationError("Arkham API key rejected (401)", address=addr)
        if response.status_code == 403:
            raise ConfigurationError("Arkham API forbidden (403) — trial/plan limits?", address=addr)
        if response.status_code == 404:
            artifact = self._empty_artifact(addr, request_id, operator_id)
            await asyncio.to_thread(
                self._persist_artifact, artifact, run_id=run_id, raw={"status": 404}
            )
            return ArkhamCollectResult(
                request_id=request_id,
                address=addr,
                from_cache=False,
                http_status_code=404,
                artifact=artifact,
            )
        if response.status_code >= 400:
            raise NetworkError(
                f"Arkham lookup failed HTTP {response.status_code}",
                address=addr,
                status_code=response.status_code,
                body=response.text[:2000],
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise NetworkError("Arkham returned non-JSON payload", address=addr) from exc

        artifact = self._normalize_payload(
            payload,
            address=addr,
            request_id=request_id,
            operator_id=operator_id,
            preferred_chain=chain,
        )
        rag_path, _rag_id = await asyncio.to_thread(self._write_rag_report, artifact)
        artifact.rag_doc_path = str(rag_path)
        await asyncio.to_thread(self._persist_artifact, artifact, run_id=run_id, raw=payload)

        if self._settings.audit_enabled:
            await asyncio.to_thread(
                self._audit.write_redteam_audit,
                request_id=request_id,
                tool="arkham_collector",
                operator_id=operator_id,
                action="lookup_address",
                outcome="pass",
                payload_hash=sha256_payload(
                    {
                        "address": addr,
                        "entity_id": artifact.entity_id,
                        "chains": artifact.chains_seen,
                    }
                ),
                duration_ms=duration_ms,
                run_id=run_id,
            )

        logger.warning(
            "Arkham intel address=%s entity=%s label=%s chains=%s",
            addr,
            artifact.entity_name or "-",
            artifact.label_name or "-",
            ",".join(artifact.chains_seen) or "-",
        )
        return ArkhamCollectResult(
            request_id=request_id,
            address=addr,
            from_cache=False,
            http_status_code=response.status_code,
            artifact=artifact,
        )

    def get_cached_artifact(self, address: str) -> ArkhamAddressArtifact | None:
        ttl = int(self._settings.arkham_cache_ttl_sec)
        row = self._db.fetchone(
            """
            SELECT artifact_id, request_id, operator_id, address, chain, entity_name,
                   entity_id, entity_type, label_name, is_contract, is_user_address,
                   chains_seen, labels, raw_payload, rag_doc_path, collected_at
            FROM arkham_recon_artifacts
            WHERE LOWER(address) = LOWER(:address)
              AND collected_at >= NOW() - (:ttl * INTERVAL '1 second')
            ORDER BY collected_at DESC
            LIMIT 1
            """,
            {"address": address, "ttl": ttl},
        )
        if not row:
            return None
        raw = row.get("raw_payload") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        chain_intel = self._chain_intel_from_raw(raw, address=address)
        return ArkhamAddressArtifact(
            artifact_id=row["artifact_id"],
            request_id=row["request_id"],
            operator_id=row["operator_id"],
            address=row["address"],
            primary_chain=row.get("chain"),
            entity_name=row.get("entity_name"),
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            label_name=row.get("label_name"),
            is_contract=row.get("is_contract"),
            is_user_address=row.get("is_user_address"),
            chains_seen=list(row.get("chains_seen") or []),
            labels=list(row.get("labels") or []),
            chain_intel=chain_intel,
            raw_payload=raw if isinstance(raw, dict) else {},
            rag_doc_path=row.get("rag_doc_path"),
            collected_at=row.get("collected_at") or _utcnow(),
        )

    @staticmethod
    def _empty_artifact(
        address: str,
        request_id: UUID,
        operator_id: str,
    ) -> ArkhamAddressArtifact:
        return ArkhamAddressArtifact(
            artifact_id=uuid4(),
            request_id=request_id,
            operator_id=operator_id,
            address=address,
            raw_payload={},
        )

    def _normalize_payload(
        self,
        payload: Any,
        *,
        address: str,
        request_id: UUID,
        operator_id: str,
        preferred_chain: str | None,
    ) -> ArkhamAddressArtifact:
        chain_intel = self._chain_intel_from_raw(payload, address=address)
        primary: ArkhamChainIntelligence | None = None
        if preferred_chain:
            primary = next((c for c in chain_intel if c.chain == preferred_chain), None)
        if primary is None and chain_intel:
            # Prefer a slice that has entity attribution.
            primary = next((c for c in chain_intel if c.entity and c.entity.name), chain_intel[0])

        entity = primary.entity if primary else None
        labels = sorted(
            {
                c.label_name
                for c in chain_intel
                if c.label_name
            }
            | ({entity.name} if entity and entity.name else set())
        )
        return ArkhamAddressArtifact(
            artifact_id=uuid4(),
            request_id=request_id,
            operator_id=operator_id,
            address=address,
            primary_chain=primary.chain if primary else preferred_chain,
            entity_name=entity.name if entity else None,
            entity_id=entity.entity_id if entity else None,
            entity_type=entity.entity_type if entity else None,
            label_name=primary.label_name if primary else None,
            is_contract=primary.is_contract if primary else None,
            is_user_address=primary.is_user_address if primary else None,
            chains_seen=[c.chain for c in chain_intel],
            labels=[label for label in labels if label],
            chain_intel=chain_intel,
            raw_payload=payload if isinstance(payload, dict) else {"data": payload},
        )

    @classmethod
    def _chain_intel_from_raw(
        cls,
        payload: Any,
        *,
        address: str,
    ) -> list[ArkhamChainIntelligence]:
        items: list[ArkhamChainIntelligence] = []
        if isinstance(payload, dict) and (
            "arkhamEntity" in payload
            or ("address" in payload and "chain" in payload and "arkhamLabel" in payload)
        ):
            # Single-chain response
            slice_ = cls._parse_chain_slice(payload, fallback_address=address)
            if slice_ is not None:
                items.append(slice_)
            return items
        if isinstance(payload, dict):
            for chain_name, body in payload.items():
                if not isinstance(body, dict):
                    continue
                # Skip non-chain metadata keys
                if chain_name in {"address", "arkhamEntity", "arkhamLabel", "error"}:
                    continue
                slice_ = cls._parse_chain_slice(
                    body,
                    fallback_address=address,
                    fallback_chain=str(chain_name),
                )
                if slice_ is not None:
                    items.append(slice_)
        return items

    @staticmethod
    def _parse_chain_slice(
        body: dict[str, Any],
        *,
        fallback_address: str,
        fallback_chain: str | None = None,
    ) -> ArkhamChainIntelligence | None:
        if not isinstance(body, dict):
            return None
        chain = str(body.get("chain") or fallback_chain or "").strip()
        if not chain:
            return None
        entity_raw = body.get("arkhamEntity") or body.get("entity")
        entity: ArkhamEntityRef | None = None
        if isinstance(entity_raw, dict):
            entity = ArkhamEntityRef(
                entity_id=entity_raw.get("id"),
                name=entity_raw.get("name"),
                entity_type=entity_raw.get("type"),
                website=entity_raw.get("website"),
                twitter=entity_raw.get("twitter"),
                note=entity_raw.get("note"),
            )
        label_raw = body.get("arkhamLabel") or body.get("label")
        label_name = None
        if isinstance(label_raw, dict):
            label_name = label_raw.get("name")
        elif isinstance(label_raw, str):
            label_name = label_raw
        return ArkhamChainIntelligence(
            chain=chain,
            address=str(body.get("address") or fallback_address),
            label_name=label_name,
            is_contract=body.get("contract") if "contract" in body else body.get("is_contract"),
            is_user_address=body.get("isUserAddress")
            if "isUserAddress" in body
            else body.get("is_user_address"),
            entity=entity,
        )

    def _persist_artifact(
        self,
        artifact: ArkhamAddressArtifact,
        *,
        run_id: UUID | None,
        raw: dict[str, Any] | Any,
    ) -> None:
        raw_payload = raw if isinstance(raw, dict) else artifact.raw_payload
        self._db.execute(
            """
            INSERT INTO arkham_recon_artifacts (
                artifact_id, request_id, run_id, operator_id, address, chain,
                entity_name, entity_id, entity_type, label_name, is_contract,
                is_user_address, chains_seen, labels, raw_payload, rag_doc_path,
                collected_at
            ) VALUES (
                :artifact_id, :request_id, :run_id, :operator_id, :address, :chain,
                :entity_name, :entity_id, :entity_type, :label_name, :is_contract,
                :is_user_address, :chains_seen, :labels, CAST(:raw_payload AS jsonb),
                :rag_doc_path, :collected_at
            )
            ON CONFLICT (artifact_id) DO UPDATE SET
                raw_payload = EXCLUDED.raw_payload,
                entity_name = EXCLUDED.entity_name,
                entity_id = EXCLUDED.entity_id,
                labels = EXCLUDED.labels,
                rag_doc_path = EXCLUDED.rag_doc_path
            """,
            {
                "artifact_id": str(artifact.artifact_id),
                "request_id": str(artifact.request_id),
                "run_id": str(run_id) if run_id else None,
                "operator_id": artifact.operator_id,
                "address": artifact.address,
                "chain": artifact.primary_chain,
                "entity_name": artifact.entity_name,
                "entity_id": artifact.entity_id,
                "entity_type": artifact.entity_type,
                "label_name": artifact.label_name,
                "is_contract": artifact.is_contract,
                "is_user_address": artifact.is_user_address,
                "chains_seen": artifact.chains_seen,
                "labels": artifact.labels,
                "raw_payload": json.dumps(raw_payload, ensure_ascii=False),
                "rag_doc_path": artifact.rag_doc_path,
                "collected_at": artifact.collected_at.isoformat(),
            },
        )

    def _write_rag_report(self, artifact: ArkhamAddressArtifact) -> tuple[Path, UUID | None]:
        rag_dir = Path(self._settings.rag_docs_path) / "emulation"
        rag_dir.mkdir(parents=True, exist_ok=True)
        rag_path = rag_dir / f"arkham_{artifact.address}_{artifact.artifact_id}.md"
        chain_lines: list[str] = []
        for slice_ in artifact.chain_intel:
            ent = slice_.entity.name if slice_.entity and slice_.entity.name else "-"
            chain_lines.append(
                f"- **{slice_.chain}**: label=`{slice_.label_name or '-'}` "
                f"entity=`{ent}` contract={slice_.is_contract}"
            )
        if not chain_lines:
            chain_lines = ["_No chain intelligence returned._"]

        rag_path.write_text(
            "\n".join(
                [
                    f"# Arkham Address Intelligence `{artifact.address}`",
                    "",
                    f"- **Artifact:** `{artifact.artifact_id}`",
                    f"- **Operator:** `{artifact.operator_id}`",
                    f"- **Primary chain:** `{artifact.primary_chain or 'unknown'}`",
                    f"- **Entity:** `{artifact.entity_name or '-'}` "
                    f"(`{artifact.entity_id or '-'}` / `{artifact.entity_type or '-'}`)",
                    f"- **Label:** `{artifact.label_name or '-'}`",
                    f"- **Contract:** {artifact.is_contract}",
                    f"- **User address:** {artifact.is_user_address}",
                    f"- **Labels:** {', '.join(f'`{label}`' for label in artifact.labels) or '-'}",
                    "",
                    "## Per-chain attribution",
                    *chain_lines,
                    "",
                    "## Raw payload",
                    "```json",
                    json.dumps(artifact.raw_payload, indent=2, ensure_ascii=False)[:12000],
                    "```",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        rag_doc_id: UUID | None = None
        try:
            rag_doc_id = self._ingester.ingest_path(
                rag_path,
                doc_type="emulation_result",
                project=self._settings.project,
                environment=self._settings.environment,
                tags=["arkham", "on_chain_osint", "address_intelligence"],
                confidence=0.9 if artifact.entity_name else 0.5,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG ingest failed for Arkham report %s: %s", rag_path, exc)
        return rag_path, rag_doc_id
