"""Financial guardrail middleware deploy/test/teardown (ADR-005)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from samson.core.config import SamsonSettings, get_settings
from samson.core.database import AuditRepository, Database, sha256_payload
from samson.core.errors import ApprovalRequiredError
from samson.core.http_client import SamsonHttpClient
from samson.core.scope import ScopeEnforcer
from samson.redteam.financial_sandbox import FinancialSandboxAgent
from samson.redteam.pyrit.risk_engine import PyRITRiskEngine
from samson.redteam.schemas import (
    FinancialGuardrailRequest,
    FinancialGuardrailResult,
    FinancialSandboxRequest,
    PyRITRiskRequest,
)

logger = logging.getLogger(__name__)

_POLICY_PROFILES = {
    "strict": [
        "iban_allowlist_enforced",
        "block_beneficiary_mismatch",
        "block_prompt_payment_injection",
        "max_transfer_eur_10000",
    ],
    "balanced": ["iban_allowlist_enforced", "max_transfer_eur_25000"],
    "permissive": ["log_only_beneficiary_mismatch"],
}


class FinancialGuardrailAgent:
    def __init__(self, settings: SamsonSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db = Database(self._settings)
        self._audit = AuditRepository(self._db)
        self._scope = ScopeEnforcer(self._settings)
        self._http = SamsonHttpClient(self._settings)
        self._sandbox = FinancialSandboxAgent(self._settings)
        self._pyrit = PyRITRiskEngine(self._settings)

    def close(self) -> None:
        self._sandbox.close()
        self._http.close()

    def run(self, req: FinancialGuardrailRequest) -> FinancialGuardrailResult:
        self._scope.assert_operator(req.operator_id, request_id=req.request_id)
        if self._settings.require_human_approval and req.action == "deploy":
            row = self._db.fetchone(
                "SELECT status FROM exercise_runs WHERE run_id = :run_id",
                {"run_id": str(req.run_id)},
            )
            if not row or row.get("status") != "approved":
                raise ApprovalRequiredError("Guardrail deploy requires approved run", run_id=str(req.run_id))

        start = time.perf_counter()
        deployment_id = uuid4()
        rules = _POLICY_PROFILES[req.policy_profile]
        pre_blocks = 0
        post_blocks = 0
        status: str = "active"

        guardrail_url = f"{self._settings.arena_base_url_str}/api/v1/financial-guardrail"
        self._scope.assert_url_in_scope(guardrail_url, request_id=req.request_id)

        if req.action == "deploy":
            self._http.post_json(
                f"{guardrail_url}/deploy",
                {
                    "deployment_id": str(deployment_id),
                    "simulation_id": str(req.simulation_id),
                    "policy_profile": req.policy_profile,
                    "rules": rules,
                },
            )
            self._db.execute(
                """
                INSERT INTO financial_guardrail_deployments (
                    deployment_id, simulation_id, policy_profile, rules_applied, status
                ) VALUES (
                    :deployment_id, :simulation_id, :policy_profile, :rules_applied::jsonb, 'active'
                )
                """,
                {
                    "deployment_id": str(deployment_id),
                    "simulation_id": str(req.simulation_id),
                    "policy_profile": req.policy_profile,
                    "rules_applied": json.dumps(rules),
                },
            )

        if req.action == "test":
            pre = self._sandbox.run(
                FinancialSandboxRequest(
                    request_id=uuid4(),
                    run_id=req.run_id,
                    operator_id=req.operator_id,
                    scenario_id=str(req.simulation_id),
                    technique="beneficiary_swap",
                    mock_merchant_id="MERCHANT_SYNTH_001",
                    environment=self._settings.environment,
                    variables={"iban_to": "DE00999999999999999999", "amount_eur": 5000},
                )
            )
            pre_blocks = 0 if pre.substitution_detected else 1
            self._http.post_json(
                f"{guardrail_url}/deploy",
                {
                    "deployment_id": str(deployment_id),
                    "simulation_id": str(req.simulation_id),
                    "policy_profile": "strict",
                    "rules": _POLICY_PROFILES["strict"],
                },
            )
            post = self._sandbox.run(
                FinancialSandboxRequest(
                    request_id=uuid4(),
                    run_id=req.run_id,
                    operator_id=req.operator_id,
                    scenario_id=str(req.simulation_id),
                    technique="beneficiary_swap",
                    mock_merchant_id="MERCHANT_SYNTH_001",
                    environment=self._settings.environment,
                    variables={"iban_to": "DE00999999999999999999", "amount_eur": 5000},
                )
            )
            post_blocks = 1 if post.substitution_detected else 0

        if req.action == "teardown":
            self._http.post_json(
                f"{guardrail_url}/teardown",
                {"deployment_id": str(deployment_id), "simulation_id": str(req.simulation_id)},
            )
            status = "destroyed"
            self._db.execute(
                """
                UPDATE financial_guardrail_deployments
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE simulation_id = :simulation_id AND status = 'active'
                """,
                {"simulation_id": str(req.simulation_id)},
            )

        pyrit_post_score = None
        if req.action in {"deploy", "test"}:
            pyrit = self._pyrit.evaluate(
                PyRITRiskRequest(
                    request_id=uuid4(),
                    scenario_id=str(req.simulation_id),
                    scenario_draft={"guardrail_profile": req.policy_profile, "rules": rules},
                    environment=self._settings.environment,
                    operator_id=req.operator_id,
                )
            )
            pyrit_post_score = pyrit.risk_score

        duration_ms = int((time.perf_counter() - start) * 1000)
        if self._settings.audit_enabled:
            self._audit.write_redteam_audit(
                request_id=req.request_id,
                tool="financial_guardrail",
                operator_id=req.operator_id,
                action=req.action,
                outcome="pass",
                payload_hash=sha256_payload(req.model_dump(mode="json")),
                duration_ms=duration_ms,
                run_id=req.run_id,
            )

        return FinancialGuardrailResult(
            request_id=req.request_id,
            deployment_id=deployment_id,
            action=req.action,
            rules_applied=rules,
            pre_block_events=pre_blocks,
            post_block_events=post_blocks,
            pyrit_post_score=pyrit_post_score,
            status=status,  # type: ignore[arg-type]
            completed_at=datetime.now(tz=timezone.utc),
        )
