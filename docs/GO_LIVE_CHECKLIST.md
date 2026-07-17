# Go-Live Gate Checklist (HexStrike)

> Decision policy: **FAIL-CLOSED**.  
> If any Critical gate is not PASS → **NO-GO**.

Technical implementation map: [`docs/GO-LIVE-MERGE-GATE-CHECKLIST.md`](GO-LIVE-MERGE-GATE-CHECKLIST.md)  
CI: `.github/workflows/policy-gate.yml` + `.github/workflows/go-live-merge-gate.yml`

## 0) Scope & Legality (Critical)

- [ ] Tx execution is limited to wallets/keys we are authorized to operate.
- [ ] Third-party wallets are intel/read-only only (no signing/broadcast path).
- [ ] Environment scope is explicitly documented (sandbox vs production-like).

## 1) Compromised Funder/Destination Defense (Critical)

- [ ] `destination_allowlist` enforced in execution path.
- [ ] `funder_allowlist` enforced in execution path.
- [ ] Negative tests prove non-allowlisted destination/funder is blocked.
- [ ] Guard event emits `BLOCK_COMPROMISED_FUNDER` (or equivalent) on deny.

## 2) TOCTOU Controls (Critical)

- [ ] `intent_hash = H(chainId,to,value,data,nonce,policyVersion)` computed before sign.
- [ ] Nonce reservation/lock enabled (no concurrent nonce race).
- [ ] Single-flight mutex enabled per wallet/executor.
- [ ] Post-sign, pre-broadcast direct/quorum recheck (balance + nonce + intent parity).
- [ ] Mismatch/drift triggers hard drop + critical alert.

## 3) Replay Resistance (Critical)

- [ ] Broadcast dedup by `(intent_hash, nonce, chainId)`.
- [ ] Re-submit with mutated intent is rejected.
- [ ] Cross-chain replay prevented by chain binding.

## 4) Key Management (Critical)

- [ ] No raw private keys in app env/CI.
- [ ] Signing uses KMS/HSM/remote signer only.
- [ ] Signer access is policy-scoped + auditable.

## 5) RPC Trust Model (Critical)

- [ ] Multi-RPC configured (>=3 providers recommended).
- [ ] Quorum validation enabled (2/3 minimum) for critical reads.
- [ ] Single-provider disagreement results in fail-closed behavior.

## 6) Transaction Risk Limits (Critical)

- [ ] Per-tx value cap enabled.
- [ ] Per-window/day cap enabled.
- [ ] Cooldown enabled after risk events.
- [ ] Emergency kill switch tested and operational.

## 7) Detection & Response (High)

- [ ] Critical alerts route to paging/on-call (not jsonl-only).
- [ ] Runbook exists for block/rollback/recovery.
- [ ] At least one incident drill executed successfully.

## 8) Rollout Phases (Critical)

### Phase A — Shadow (no sign, no broadcast)

- [ ] Guard decisions stable on real telemetry.

### Phase B — Dry-sign (sign only, no broadcast)

- [ ] Signer integration stable, audit logs complete.

### Phase C — Canary Live (tiny value)

- [ ] Limited to allowlisted destination(s).
- [ ] Strict tiny budget + short observation window.
- [ ] Any critical alert auto-disables broadcast.

### Phase D — Limited Production

- [ ] Limits increased gradually with explicit approvals.
- [ ] No critical policy violations during canary window.

---

## Final Decision

- **GO** only if all Critical items PASS.
- Otherwise **NO-GO** and open remediation issues.
