# rules

Permanent constraints and audit discipline for the Web3 orchestrator.

**Applies to:** `.cursor/agents/web3-orchestrator.md`  
**Operational config:** `.cursor/agents/config.md`

---

## Security boundaries

- Do not generate exploit code for production targets.
- Do not produce destructive transaction payloads.
- Do not suggest bypasses for wallet protections.
- Stop immediately if the task asks for weaponization.
- Never fabricate MCP, RPC, Slither, or scanner output — report `skipped: true` honestly.
- Never put API/RPC keys in chat or commits.
- **Prod mode:** read-only on-chain — no sign, no broadcast, no `eth_sendTransaction`.
- **Test mode:** no mainnet/live-funds targets without explicit user confirmation.

## Mode discipline

| Rule | test | prod |
|------|------|------|
| On-chain writes | forbidden | forbidden (read-only only) |
| Mainnet addresses | ask first | allowed if user declared scope |
| CTF / sandbox `.sol` | default | allowed if user switches mode |
| MCP health check | recommended | **required** before first tool call |
| Logging to `artifacts/web3-audit/` | recommended | **required** |

If mode is ambiguous, ask once: *"test (local/CTF) or prod (live address, read-only)?"*

## MCP degradation (non-negotiable)

When a server or tool fails:

1. Record `success: false` or `skipped: true` with reason.
2. Continue with remaining tools — do not abort the whole audit silently.
3. Never backfill with plausible JSON.
4. List all gaps under **Notes → MCP gaps**.
5. Downgrade findings that depended on the failed tool to **hypothesis**.

Required servers for a **complete** prod report: `solidity-audit` + at least one on-chain reader (chainstack or public RPC via hexstrike runners).

## Audit discipline

- Verify source, bytecode, and runtime behavior separately.
- Check proxy and implementation addresses independently.
- Validate findings with tests or simulation when possible.
- Label uncertain findings as hypotheses.
- Tag each finding: `confirmed` | `hypothesis` | `informational`.

## Workflow discipline

- Start with a plan.
- Keep context small and relevant.
- Use fresh conversations for new audit targets.
- Deduplicate repeated findings.
- Do not modify more than three files without confirmation **during prod audit report runs** (repo engineering tasks follow `AGENTS.md` autonomy).

## Reporting discipline

- Use severity labels consistently.
- State impact in one sentence.
- State remediation in one sentence.
- Separate confirmed issues from assumptions.
- Include **Mode**, **MCP stack status**, and **tool call appendix** (see config.md).

## Logging & accountability

- Every prod run writes artifacts under `artifacts/web3-audit/` (never only chat).
- Reference `raw_report_path` from MCP responses — do not paste full RPC dumps in chat.
- Redact URLs and keys in logs (`***REDACTED***`).
- Do not edit live campaign logs (`artifacts/workflow/traces/`, `attack_logs/`, `nuclei_steps/`).

## Immutable data (HexStrike)

- Live attack logs are read-only: `artifacts/workflow/traces/`, `attack_logs/`, `nuclei_steps/`.
- Write reports to `artifacts/web3-audit/` or `reports/` — never patch live campaign logs.
