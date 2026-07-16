"""Pydantic schemas for Samson red-team modules.

Core adversary-emulation contract (target context, payloads, execution results,
guardrail config) plus ADR-003 through ADR-005 orchestration schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Core adversary-emulation contract (foundation)
# =============================================================================


class AdversaryTargetContext(BaseModel):
    """Contract for the AI system under test and its network interfaces."""

    target_id: UUID
    target_endpoint: HttpUrl = Field(..., description="Real URL of the AI model or agent API under audit")
    interface_type: str = Field(
        ...,
        description="Stripe-Gateway, Plaid-Integration, REST-LLM-API, IBAN-Parser",
    )
    auth_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Authorization tokens and headers for network requests",
    )
    vector_db_connected: bool = False


class ExecutionPayload(BaseModel):
    """Generated payload structure for business-logic resilience testing."""

    payload_id: UUID
    attack_vector: str = Field(
        ...,
        description="Vulnerability class: Indirect_Prompt_Injection, Adversarial_Noise, Context_Bleed",
    )
    raw_payload_data: str = Field(..., description="Raw injection data sent in the HTTP request")
    generated_at: datetime = Field(default_factory=_utcnow)


class AdversaryEmulationResult(BaseModel):
    """Result of a network security test execution."""

    execution_id: UUID
    vulnerability_verified: bool = Field(
        ...,
        description="Whether model constraints were successfully bypassed",
    )
    http_status_code: int
    response_payload: dict[str, Any] = Field(
        ...,
        description="Raw target system response for analysis of extracted data",
    )
    intercepted_financial_entities: list[str] = Field(
        default_factory=list,
        description="Financial identifiers found in response (IBAN, tokens, masked cards)",
    )


class GuardrailEnforcementConfig(BaseModel):
    """Guardrail gateway parameters derived from test results."""

    config_id: UUID
    strict_regex_patterns: list[str] = Field(
        ...,
        description="Regex patterns blocking credential leakage to external networks",
    )
    allowed_destination_hosts: list[str] = Field(
        ...,
        description="Allowlist of domains for outbound AI agent calls",
    )
    enforce_human_approval: bool = True


# =============================================================================
# ADR-003 PyRIT
# =============================================================================


class PyRITRiskRequest(BaseModel):
    request_id: UUID
    scenario_id: str
    scenario_draft: dict
    atlas_techniques: list[str] = Field(default_factory=list)
    target_profile: dict = Field(default_factory=dict)
    environment: Literal["dev", "stage", "prod"]
    operator_id: str
    target_context: AdversaryTargetContext | None = None


class PyRITRiskResult(BaseModel):
    request_id: UUID
    risk_score: float
    risk_band: Literal["low", "medium", "high", "critical"]
    harm_categories: list[str]
    blocked: bool
    requires_elevated_approval: bool
    rationale: str
    pyrit_report_path: str
    scanned_at: datetime


# =============================================================================
# ADR-003 Garak
# =============================================================================


class GarakScanRequest(BaseModel):
    request_id: UUID
    model_endpoint: str
    model_name: str
    probe_suite: Literal["full", "fast", "custom"] = "fast"
    environment: Literal["dev", "stage", "prod"]
    triggered_by: Literal["schedule", "model_change", "pre_exercise", "manual"]
    target_context: AdversaryTargetContext | None = None


class GarakFinding(BaseModel):
    probe_name: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    description: str
    evidence: str
    mitre_atlas_technique: str | None = None


class GarakScanResult(BaseModel):
    request_id: UUID
    scan_id: UUID
    model_name: str
    probes_run: int
    probes_failed: int
    hit_rate: float
    findings: list[GarakFinding]
    garak_report_path: str
    scanned_at: datetime


# =============================================================================
# ADR-003 ATLAS
# =============================================================================


class ATLASMapRequest(BaseModel):
    request_id: UUID
    artifact_type: Literal["scenario_draft", "telemetry", "garak_finding", "pyrit_report", "financial_impact"]
    artifact: dict
    top_k: int = 5


class ATLASEntry(BaseModel):
    atlas_id: str
    name: str
    description: str
    confidence: float
    evidence: str


class ATLASMapResult(BaseModel):
    request_id: UUID
    tactics: list[ATLASEntry]
    techniques: list[ATLASEntry]
    mitigations: list[str]
    confidence: float
    taxonomy_version: str


# =============================================================================
# ADR-004 Impact
# =============================================================================


class ImpactSimulationRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    operator_id: str
    scenario_id: str
    atlas_techniques: list[str] = Field(default_factory=list)
    arena_target_id: str
    simulation_profile: Literal["persistence", "data_access", "lateral_movement", "full_chain", "financial_impact"]
    environment: Literal["dev", "stage", "prod"]
    payload_ids: list[str] = Field(default_factory=list)
    variables: dict = Field(default_factory=dict)
    target_context: AdversaryTargetContext | None = None
    execution_payloads: list[ExecutionPayload] = Field(default_factory=list)


class ImpactSimulationResult(BaseModel):
    request_id: UUID
    simulation_id: UUID
    run_id: UUID
    phases_executed: list[str]
    synthetic_artifacts_accessed: list[str]
    atlas_mappings: list[str]
    impact_summary: str
    reversible: bool
    audit_path: str
    payload_results: list[dict] = Field(default_factory=list)
    emulation_results: list[AdversaryEmulationResult] = Field(default_factory=list)
    completed_at: datetime


class RemediationDemoRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    simulation_id: UUID | None = None
    operator_id: str
    demo_type: Literal["impact_protection_report", "remediation_walkthrough", "guardrail_container"]
    audience: Literal["operator", "leadership", "blue_team"]
    guardrail_config: GuardrailEnforcementConfig | None = None


class RemediationDemoResult(BaseModel):
    request_id: UUID
    demo_id: UUID
    report_id: UUID
    report_path: str
    guardrail_deployment_id: UUID | None = None
    pyrit_post_score: float | None = None
    citations: list[str]
    guardrail_config: GuardrailEnforcementConfig | None = None
    completed_at: datetime


# =============================================================================
# ADR-005 Financial
# =============================================================================


class FinancialSandboxRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    operator_id: str
    scenario_id: str
    technique: Literal["invoice_substitution", "payment_api_abuse", "beneficiary_swap", "llm_payment_injection"]
    mock_merchant_id: str
    environment: Literal["dev", "stage", "prod"]
    payload_id: str | None = None
    variables: dict = Field(default_factory=dict)
    target_context: AdversaryTargetContext | None = None
    execution_payload: ExecutionPayload | None = None


class FinancialSandboxResult(BaseModel):
    request_id: UUID
    simulation_id: UUID
    technique: str
    mock_transactions: list[dict]
    synthetic_amount_eur: float
    substitution_detected: bool
    ledger_snapshot_path: str
    atlas_technique_ids: list[str]
    payload_results: list[dict] = Field(default_factory=list)
    emulation_result: AdversaryEmulationResult | None = None
    completed_at: datetime


class FinancialGuardrailRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    simulation_id: UUID
    operator_id: str
    action: Literal["deploy", "test", "teardown"]
    policy_profile: Literal["strict", "balanced", "permissive"]
    guardrail_config: GuardrailEnforcementConfig | None = None


class FinancialGuardrailResult(BaseModel):
    request_id: UUID
    deployment_id: UUID
    action: str
    rules_applied: list[str]
    pre_block_events: int
    post_block_events: int
    pyrit_post_score: float | None = None
    status: Literal["active", "teardown", "destroyed"]
    guardrail_config: GuardrailEnforcementConfig | None = None
    completed_at: datetime


__all__ = [
    "AdversaryTargetContext",
    "ExecutionPayload",
    "AdversaryEmulationResult",
    "GuardrailEnforcementConfig",
    "PyRITRiskRequest",
    "PyRITRiskResult",
    "GarakScanRequest",
    "GarakFinding",
    "GarakScanResult",
    "ATLASMapRequest",
    "ATLASEntry",
    "ATLASMapResult",
    "ImpactSimulationRequest",
    "ImpactSimulationResult",
    "RemediationDemoRequest",
    "RemediationDemoResult",
    "FinancialSandboxRequest",
    "FinancialSandboxResult",
    "FinancialGuardrailRequest",
    "FinancialGuardrailResult",
]
