"""Pydantic schemas for Samson red-team modules (ADR-003 through ADR-005)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# --- ADR-003 PyRIT ---
class PyRITRiskRequest(BaseModel):
    request_id: UUID
    scenario_id: str
    scenario_draft: dict
    atlas_techniques: list[str] = Field(default_factory=list)
    target_profile: dict = Field(default_factory=dict)
    environment: Literal["dev", "stage", "prod"]
    operator_id: str


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


# --- ADR-003 Garak ---
class GarakScanRequest(BaseModel):
    request_id: UUID
    model_endpoint: str
    model_name: str
    probe_suite: Literal["full", "fast", "custom"] = "fast"
    environment: Literal["dev", "stage", "prod"]
    triggered_by: Literal["schedule", "model_change", "pre_exercise", "manual"]


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


# --- ADR-003 ATLAS ---
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


# --- ADR-004 Impact ---
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
    completed_at: datetime


class RemediationDemoRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    simulation_id: UUID | None = None
    operator_id: str
    demo_type: Literal["impact_protection_report", "remediation_walkthrough", "guardrail_container"]
    audience: Literal["operator", "leadership", "blue_team"]


class RemediationDemoResult(BaseModel):
    request_id: UUID
    demo_id: UUID
    report_id: UUID
    report_path: str
    guardrail_deployment_id: UUID | None = None
    pyrit_post_score: float | None = None
    citations: list[str]
    completed_at: datetime


# --- ADR-005 Financial ---
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
    completed_at: datetime


class FinancialGuardrailRequest(BaseModel):
    request_id: UUID
    run_id: UUID
    simulation_id: UUID
    operator_id: str
    action: Literal["deploy", "test", "teardown"]
    policy_profile: Literal["strict", "balanced", "permissive"]


class FinancialGuardrailResult(BaseModel):
    request_id: UUID
    deployment_id: UUID
    action: str
    rules_applied: list[str]
    pre_block_events: int
    post_block_events: int
    pyrit_post_score: float | None = None
    status: Literal["active", "teardown", "destroyed"]
    completed_at: datetime
