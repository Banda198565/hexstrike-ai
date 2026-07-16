"""Desktop / on-prem target pool ingestion for Samson SBM bulk audits.

Scans the authorized macOS desktop folder (Cyrillic label) with a container
fallback path, extracts unique IPs / domains / URLs from operator documents,
and materializes them as strict Pydantic models ready for continuous-audit.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator

from samson.core.errors import ConfigurationError
from samson.redteam.schemas import AdversaryTargetContext, ContinuousAuditRequest

logger = logging.getLogger(__name__)

DESKTOP_TARGET_DIRNAME = "тест ЦЕЛИ"
CONTAINER_FALLBACK_ROOT = Path("/data/pentest/targets")

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".xml",
    ".log",
    ".conf",
    ".cfg",
    ".ini",
    ".list",
    ".url",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_IPV4_RE = re.compile(
    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?![\w.])"
)
_DOMAIN_RE = re.compile(
    r"(?<![\w./-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})(?::\d{2,5})?(?![\w.-])",
    re.IGNORECASE,
)

_SKIP_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "localdomain",
    "invalid",
    "test",
}

_HTTP_PORTS = {80, 8080, 8000, 8888, 3000, 5000, 7001, 9000}
_HTTPS_PORTS = {443, 8443, 9443}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestedTargetKind(str, Enum):
    IP = "ip"
    DOMAIN = "domain"
    URL = "url"


class IngestedTarget(BaseModel):
    """Normalized engagement target extracted from operator documents."""

    target_id: UUID = Field(default_factory=uuid4)
    kind: IngestedTargetKind
    raw_value: str
    normalized_value: str
    source_files: list[str] = Field(default_factory=list)
    ip_address: str | None = None
    domain: str | None = None
    port: int | None = None
    audit_endpoint: HttpUrl | None = None
    interface_type: str = "IBAN-Parser"
    open_ports: list[int] = Field(default_factory=list)
    detected_vulnerabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("normalized_value")
    @classmethod
    def _strip_normalized(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("normalized_value must be non-empty")
        return text

    def to_adversary_context(
        self,
        *,
        auth_headers: dict[str, str] | None = None,
    ) -> AdversaryTargetContext:
        endpoint = self.audit_endpoint
        if endpoint is None:
            raise ConfigurationError(
                "Ingested target has no audit_endpoint; call resolve_audit_endpoints first",
                target=self.normalized_value,
            )
        return AdversaryTargetContext(
            target_id=self.target_id,
            target_endpoint=endpoint,
            interface_type=self.interface_type,
            auth_headers=dict(auth_headers or {}),
        )

    def to_continuous_audit_request(
        self,
        *,
        operator_id: str,
        scenario_id: str = "bulk-continuous-audit",
        run_id: UUID | None = None,
        auth_headers: dict[str, str] | None = None,
        policy_profile: str = "strict",
        request_id: UUID | None = None,
    ) -> ContinuousAuditRequest:
        endpoint = self.audit_endpoint
        if endpoint is None:
            raise ConfigurationError(
                "Ingested target has no audit_endpoint; call resolve_audit_endpoints first",
                target=self.normalized_value,
            )
        return ContinuousAuditRequest(
            request_id=request_id or uuid4(),
            target_endpoint=endpoint,
            interface_type=self.interface_type,
            operator_id=operator_id,
            scenario_id=scenario_id,
            run_id=run_id,
            auth_headers=dict(auth_headers or {}),
            policy_profile=policy_profile,  # type: ignore[arg-type]
        )


class IngestedTargetPool(BaseModel):
    """Complete pool of unique targets from one filesystem scan."""

    source_root: str
    scanned_files: int = 0
    skipped_files: int = 0
    targets: list[IngestedTarget] = Field(default_factory=list)
    loaded_at: datetime = Field(default_factory=_utcnow)

    @property
    def unique_count(self) -> int:
        return len(self.targets)


class TargetLoader:
    """Scan authorized target folders and emit strict Pydantic target models."""

    def __init__(
        self,
        *,
        desktop_dirname: str = DESKTOP_TARGET_DIRNAME,
        container_fallback: Path | str = CONTAINER_FALLBACK_ROOT,
        explicit_root: Path | str | None = None,
    ) -> None:
        self._desktop_dirname = desktop_dirname
        self._container_fallback = Path(container_fallback).expanduser()
        self._explicit_root = Path(explicit_root).expanduser() if explicit_root else None

    def resolve_source_root(self) -> Path:
        if self._explicit_root is not None:
            root = self._explicit_root
            if not root.is_dir():
                raise ConfigurationError(
                    f"Explicit target root does not exist: {root}",
                    path=str(root),
                )
            return root.resolve()

        desktop_root = Path.home() / "Desktop" / self._desktop_dirname
        if desktop_root.is_dir():
            logger.info("Using macOS desktop target pool: %s", desktop_root)
            return desktop_root.resolve()

        # Some environments expose the same folder via $HOME/Desktop with NFC/NFD variants
        desktop_parent = Path.home() / "Desktop"
        if desktop_parent.is_dir():
            for child in desktop_parent.iterdir():
                if child.is_dir() and child.name.casefold() == self._desktop_dirname.casefold():
                    logger.info("Using desktop target pool (casefold match): %s", child)
                    return child.resolve()

        env_root = os.environ.get("SAMSON_TARGETS_DIR") or os.environ.get("SAMSON_TARGET_POOL_DIR")
        if env_root:
            env_path = Path(env_root).expanduser()
            if env_path.is_dir():
                logger.info("Using SAMSON_TARGETS_DIR target pool: %s", env_path)
                return env_path.resolve()

        if self._container_fallback.is_dir():
            logger.info("Using container fallback target pool: %s", self._container_fallback)
            return self._container_fallback.resolve()

        raise ConfigurationError(
            "No target pool found. Expected "
            f"~/Desktop/{self._desktop_dirname} or {self._container_fallback}",
            desktop=str(desktop_root),
            fallback=str(self._container_fallback),
        )

    def load(self) -> IngestedTargetPool:
        root = self.resolve_source_root()
        files = list(self._iter_document_files(root))
        by_key: dict[str, IngestedTarget] = {}
        scanned = 0
        skipped = 0

        for path in files:
            try:
                text = self._read_text(path)
            except OSError as exc:
                logger.warning("Skipping unreadable target document %s: %s", path, exc)
                skipped += 1
                continue
            scanned += 1
            relative = str(path.relative_to(root))
            for kind, value in self.extract_indicators(text):
                key = f"{kind.value}:{value.lower()}"
                existing = by_key.get(key)
                if existing is not None:
                    if relative not in existing.source_files:
                        existing.source_files.append(relative)
                    continue
                by_key[key] = self._build_target(kind, value, source_file=relative)

        targets = sorted(by_key.values(), key=lambda t: (t.kind.value, t.normalized_value))
        for target in targets:
            self.resolve_audit_endpoint(target)

        pool = IngestedTargetPool(
            source_root=str(root),
            scanned_files=scanned,
            skipped_files=skipped,
            targets=targets,
        )
        logger.info(
            "Ingested %s unique targets from %s files under %s",
            pool.unique_count,
            pool.scanned_files,
            pool.source_root,
        )
        return pool

    @staticmethod
    def extract_indicators(text: str) -> list[tuple[IngestedTargetKind, str]]:
        found: list[tuple[IngestedTargetKind, str]] = []
        seen: set[str] = set()

        def _add(kind: IngestedTargetKind, value: str) -> None:
            normalized = TargetLoader._normalize_value(kind, value)
            if not normalized:
                return
            key = f"{kind.value}:{normalized.lower()}"
            if key in seen:
                return
            seen.add(key)
            found.append((kind, normalized))

        url_hosts: set[str] = set()
        for match in _URL_RE.finditer(text):
            raw = match.group(0).rstrip(".,;:!?")
            before = len(found)
            _add(IngestedTargetKind.URL, raw)
            if len(found) > before:
                host = urlparse(found[-1][1]).hostname
                if host:
                    url_hosts.add(host.lower())

        for match in _IPV4_RE.finditer(text):
            raw = match.group(0)
            try:
                ipaddress.IPv4Address(raw)
            except ValueError:
                continue
            # Prefer the richer URL indicator when the same host already appears.
            if raw in url_hosts:
                continue
            _add(IngestedTargetKind.IP, raw)

        for match in _DOMAIN_RE.finditer(text):
            raw = match.group(0).rstrip(".,;:!?")
            host = raw.split(":", 1)[0].lower()
            if host in _SKIP_DOMAINS or host.endswith(".example"):
                continue
            # Skip IPv4 already captured as IP
            if _IPV4_RE.fullmatch(host):
                continue
            # Skip URL hosts already captured
            if host in url_hosts:
                continue
            _add(IngestedTargetKind.DOMAIN, raw)

        return found

    @staticmethod
    def resolve_audit_endpoint(
        target: IngestedTarget,
        *,
        preferred_ports: Iterable[int] | None = None,
        interface_type: str = "IBAN-Parser",
    ) -> IngestedTarget:
        """Attach a concrete HTTP(S) audit endpoint for continuous-audit."""
        target.interface_type = interface_type
        ports = list(preferred_ports) if preferred_ports is not None else list(target.open_ports)

        if target.kind == IngestedTargetKind.URL:
            target.audit_endpoint = target.normalized_value  # type: ignore[assignment]
            parsed = urlparse(target.normalized_value)
            target.domain = parsed.hostname
            target.port = parsed.port
            if parsed.hostname:
                try:
                    ipaddress.ip_address(parsed.hostname)
                    target.ip_address = parsed.hostname
                except ValueError:
                    pass
            return target

        if target.kind == IngestedTargetKind.DOMAIN:
            host = target.normalized_value
            port: int | None = None
            if ":" in host and not host.startswith("["):
                host_part, port_part = host.rsplit(":", 1)
                if port_part.isdigit():
                    host, port = host_part, int(port_part)
            target.domain = host
            target.port = port
            if port in _HTTPS_PORTS:
                endpoint = f"https://{host}:{port}/"
            elif port:
                endpoint = f"http://{host}:{port}/"
            else:
                endpoint = f"https://{host}/"
            target.audit_endpoint = endpoint  # type: ignore[assignment]
            return target

        # IP
        ip = target.normalized_value
        target.ip_address = ip
        http_port = TargetLoader._pick_http_port(ports)
        target.port = http_port
        if http_port in _HTTPS_PORTS:
            endpoint = f"https://{ip}:{http_port}/"
        elif http_port and http_port not in (80,):
            endpoint = f"http://{ip}:{http_port}/"
        elif http_port == 80:
            endpoint = f"http://{ip}/"
        else:
            endpoint = f"http://{ip}/"
        target.audit_endpoint = endpoint  # type: ignore[assignment]
        return target

    def write_scope_overlay(
        self,
        pool: IngestedTargetPool,
        *,
        base_scope_path: Path | str,
        destination: Path | str,
    ) -> Path:
        """Authorize ingested targets for the bulk-audit engagement window."""
        base_path = Path(base_scope_path)
        if not base_path.is_file():
            raise ConfigurationError(f"Scope config not found: {base_path}", path=str(base_path))
        data = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ConfigurationError("Scope config root must be a mapping", path=str(base_path))

        targets = list(data.get("targets") or [])
        existing_ids = {str(t.get("target_id")) for t in targets if isinstance(t, dict)}
        techniques = [
            "persistence",
            "data_access",
            "lateral_movement",
            "invoice_substitution",
            "payment_api_abuse",
            "beneficiary_swap",
            "llm_payment_injection",
        ]
        agents = ["impact_simulation", "financial_sandbox", "garak", "shodan"]

        for item in pool.targets:
            if item.audit_endpoint is None:
                self.resolve_audit_endpoint(item)
            tid = f"ingested-{item.target_id.hex[:12]}"
            if tid in existing_ids:
                continue
            parsed = urlparse(str(item.audit_endpoint))
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            cidrs: list[str] = []
            if item.ip_address:
                try:
                    ip = ipaddress.ip_address(item.ip_address)
                    cidrs = [str(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False))]
                except ValueError:
                    cidrs = []
            targets.append(
                {
                    "target_id": tid,
                    "base_url": base_url,
                    "allowed_techniques": techniques,
                    "allowed_agents": agents,
                    "network_cidrs": cidrs,
                    "metadata": {
                        "type": "ingested",
                        "kind": item.kind.value,
                        "normalized": item.normalized_value,
                        "source_files": item.source_files,
                    },
                }
            )
            existing_ids.add(tid)

        data["targets"] = targets
        # Ingested desktop pool is an authorized engagement set for this run.
        data["allowed_external_egress"] = True
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("Wrote authorized scope overlay with %s targets → %s", len(targets), dest)
        return dest.resolve()

    @staticmethod
    def _pick_http_port(ports: Iterable[int]) -> int | None:
        ordered = list(ports)
        for preferred in (443, 8443, 80, 8080, 8000, 8888, 3000):
            if preferred in ordered:
                return preferred
        for port in ordered:
            if port in _HTTP_PORTS or port in _HTTPS_PORTS:
                return port
        return ordered[0] if ordered else None

    @staticmethod
    def _normalize_value(kind: IngestedTargetKind, value: str) -> str | None:
        text = value.strip().rstrip(".,;:!?")
        if not text:
            return None
        if kind == IngestedTargetKind.URL:
            if text.startswith("//"):
                text = f"http:{text}"
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return None
            path = parsed.path or "/"
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{parsed.scheme}://{parsed.netloc}{path}{query}"
        if kind == IngestedTargetKind.IP:
            try:
                return str(ipaddress.IPv4Address(text))
            except ValueError:
                return None
        # domain
        return text.lower()

    @staticmethod
    def _build_target(kind: IngestedTargetKind, value: str, *, source_file: str) -> IngestedTarget:
        ip_address = value if kind == IngestedTargetKind.IP else None
        domain = value.split(":", 1)[0] if kind == IngestedTargetKind.DOMAIN else None
        if kind == IngestedTargetKind.URL:
            host = urlparse(value).hostname
            domain = host
            if host:
                try:
                    ipaddress.ip_address(host)
                    ip_address = host
                except ValueError:
                    pass
        return IngestedTarget(
            kind=kind,
            raw_value=value,
            normalized_value=value,
            source_files=[source_file],
            ip_address=ip_address,
            domain=domain,
        )

    @staticmethod
    def _iter_document_files(root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() in _TEXT_SUFFIXES or path.suffix == "":
                yield path

    @staticmethod
    def _read_text(path: Path) -> str:
        raw = path.read_bytes()
        if not raw:
            return ""
        # Skip obvious binaries
        if b"\x00" in raw[:2048]:
            raise OSError("binary file")
        for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                return json.dumps(json.loads(text), ensure_ascii=False)
            except json.JSONDecodeError:
                return text
        if suffix in {".yaml", ".yml"}:
            try:
                loaded = yaml.safe_load(text)
                return json.dumps(loaded, ensure_ascii=False) if loaded is not None else text
            except yaml.YAMLError:
                return text
        return text
