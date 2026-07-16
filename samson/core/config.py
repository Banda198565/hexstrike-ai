"""Environment-driven configuration for Samson SBM. No hardcoded endpoints or credentials."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SamsonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SAMSON_",
        extra="ignore",
    )

    # Identity
    project: str = Field(default="samson-sbm", description="Project / tenant identifier")
    environment: Literal["dev", "stage", "prod"] = "dev"

    # PostgreSQL
    database_url: str = Field(
        default="postgresql://samson:samson@127.0.0.1:5432/samson",
        description="SQLAlchemy-compatible PostgreSQL URL",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_sec: int = 30

    # Ollama / LLM
    ollama_base_url: HttpUrl = Field(default="http://127.0.0.1:11434")
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2"
    ollama_timeout_sec: float = 120.0

    # Target Arena — authorized scope endpoints (from env / config, never hardcoded in code)
    arena_base_url: HttpUrl = Field(default="http://127.0.0.1:8080")
    arena_namespace: str = "samson-arena"
    financial_mock_stripe_url: HttpUrl | None = None
    financial_mock_iban_url: HttpUrl | None = None

    # Scope & payloads
    scope_config_path: Path = Field(default=Path("config/samson/scope.yaml"))
    payload_registry_path: Path = Field(default=Path("config/samson/payloads"))
    fixture_root_path: Path = Field(default=Path("target-arena/fixtures"))

    # RAG
    rag_chunk_size_tokens: int = 512
    rag_chunk_overlap_tokens: int = 64
    rag_docs_path: Path = Field(default=Path("samson/rag/docs"))
    rag_reports_path: Path = Field(default=Path("samson/rag/reports"))
    rag_index_version: int = 1

    # Red team tools
    pyrit_enabled: bool = True
    pyrit_config_path: Path = Field(default=Path("config/samson/pyrit.yaml"))
    pyrit_python: str = "python3"
    pyrit_block_threshold: float = 0.8
    pyrit_elevated_threshold: float = 0.6

    garak_enabled: bool = True
    garak_probe_suite: Literal["full", "fast", "custom"] = "fast"
    garak_reports_path: Path = Field(default=Path("samson/redteam/garak/reports"))

    atlas_taxonomy_path: Path = Field(default=Path("samson/redteam/atlas/taxonomy.json"))

    # HTTP client
    http_timeout_sec: float = 30.0
    http_connect_timeout_sec: float = 10.0
    http_max_retries: int = 3
    http_retry_backoff_sec: float = 1.5
    http_user_agent: str = "Samson-SBM/0.1.0 (Authorized-Red-Team)"

    # Audit
    audit_enabled: bool = True

    # Execution gate
    require_human_approval: bool = True
    prod_dual_approval: bool = True

    @field_validator("scope_config_path", "payload_registry_path", "fixture_root_path", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    @property
    def ollama_base_url_str(self) -> str:
        return str(self.ollama_base_url).rstrip("/")

    @property
    def arena_base_url_str(self) -> str:
        return str(self.arena_base_url).rstrip("/")

    def resolve_financial_stripe_url(self) -> str:
        if self.financial_mock_stripe_url is not None:
            return str(self.financial_mock_stripe_url).rstrip("/")
        return f"{self.arena_base_url_str}/mock-stripe"

    def resolve_financial_iban_url(self) -> str:
        if self.financial_mock_iban_url is not None:
            return str(self.financial_mock_iban_url).rstrip("/")
        return f"{self.arena_base_url_str}/mock-iban-validator"


@lru_cache
def get_settings() -> SamsonSettings:
    return SamsonSettings()
