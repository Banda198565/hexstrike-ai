# Final Go-Live Evidence Report

| Field | Value |
| --- | --- |
| Document | `docs/ops/FINAL-GO-LIVE-EVIDENCE-REPORT.md` |
| Checklist | `docs/GO_LIVE_CHECKLIST.md` |
| Branch / PR | `cursor/go-live-ops-evidence-f2e6` (ops pack) + `#49` real-tx/KMS |
| Reviewed at (UTC) | _operator fills_ |
| Reviewer | _operator fills_ |
| **GLOBAL VERDICT** | **NO-GO** (operator-owned Critical leftovers open) |

Policy: **FAIL-CLOSED**. Any Critical cell ≠ GO → GLOBAL NO-GO.

---

## How to use

For each Critical row: set **Verdict** to `GO` / `NO-GO`, paste **Evidence** (path, CI URL, log excerpt, screenshot path). Do not mark GO without an artifact.

---

## Critical gates matrix

| § | Gate | Verdict | Evidence (required) | Notes |
| --- | --- | --- | --- | --- |
| 0 | Scope & legality | **NO-GO** | Auth letter / scope doc path | Operator: confirm authorized wallets only |
| 1 | Compromised funder/destination (#06) | **GO** _(code)_ | PR #48/#49; `TestPrepareRescueDestinationMismatchBlocked`; `test_production_gates.py`; ARCHITECTURE `#06` DEFENDED* | Re-confirm on staging with real allowlist env |
| 2 | TOCTOU | **GO** _(code)_ | `SecureSignRescue` + `secure_sign_test.go`; intent claim + post-sign drift → kill | Staging soak still operator |
| 3 | Replay resistance | **GO** _(code)_ | Dedup `(intent_hash, nonce, chainId)` in SecureSign path | Cross-chain soak operator |
| 4a | No raw keys in app/CI | **GO** _(CI)_ | `.github/workflows/policy-gate.yml`; negative PR #47 | Keep required check on `master` |
| 4b | KMS/HSM signing only (code) | **GO** _(code)_ | `kms_aws.go` / `kms_gcp.go`; `SIGNER_BACKEND=kms`; fail-closed unit tests | — |
| 4c | Staging smoke real KMS | **NO-GO** | `artifacts/ops/kms-smoke-*/summary.json` with live PASS | Run `scripts/ops/run-kms-staging-smoke.sh` with creds — see `KMS-STAGING-SMOKE.md` |
| 4d | IAM/policy scoped + audit | **NO-GO** | Applied policy + CloudTrail/Cloud Audit sample | Templates: `docs/ops/iam/*`, `KMS-IAM-HARDENING.md` |
| 5 | RPC quorum 2/3 fail-closed | **GO** _(code)_ | Engine `RequireQuorum`; `production_gates.py` | Staging multi-provider config operator |
| 6 | Value/rate/cooldown/kill | **GO** _(code)_ | Engine limits + `OnCritical` kill; gate tests | Kill-switch drill operator |
| 7 | Paging / on-call | **NO-GO** | `artifacts/ops/paging-drill-*.json` verdict PASS + on-call ack | Wire `ALERT_*`; run `paging_drill.py` — `PAGING-ONCALL.md` |
| 8A | Shadow phase | **NO-GO** | Shadow soak report / telemetry window | Operator phase evidence |
| 8B | Dry-sign | **NO-GO** | Dry-sign audit logs (KMS) | After 4c |
| 8C | Canary live tiny value | **NO-GO** | Canary tx hash + budget proof | Only after 4c–7 + allowlist |
| 8D | Limited production | **NO-GO** | Approval + no critical violations | Last |

---

## Operator runbook (close NO-GO cells)

1. **§4c** — Create staging KMS key → apply IAM templates → `./scripts/ops/run-kms-staging-smoke.sh` → attach `summary.json`.
2. **§4d** — Apply least privilege + audit trail → attach CLI/policy evidence (redacted).
3. **§7** — Set `ALERT_PAGING_ENABLED` + webhook → `python3 scripts/ops/paging_drill.py` → attach drill JSON + ack.
4. **§0 / §8** — Legal scope + phased soak evidence.
5. Re-run this matrix → if all Critical = GO → set **GLOBAL GO** and date it.

---

## Code-side evidence index (pre-filled)

| Artifact | Path / ref |
| --- | --- |
| Allowlist / #06 | `cmd/agent/internal/orchestrator/engine_test.go`, `scripts/sandbox/test_production_gates.py` |
| SecureSign TOCTOU | `cmd/agent/internal/orchestrator/secure_sign.go` |
| AWS/GCP KMS SDK | `cmd/agent/internal/signer/kms_aws.go`, `kms_gcp.go` |
| Policy gate CI | `.github/workflows/policy-gate.yml` |
| KMS smoke harness | `scripts/ops/run-kms-staging-smoke.sh` |
| Paging sink | `scripts/sandbox/alert_paging.py`, `cmd/agent/internal/alerting/webhook.go` |
| Architecture sync | `docs/ARCHITECTURE.md` v2.2 |

---

## Sign-off

| Role | Name | Date | Verdict |
| --- | --- | --- | --- |
| Engineering | | | |
| Security / IR | | | |
| On-call owner | | | |

**GLOBAL:** NO-GO until every Critical row above is GO with evidence.
