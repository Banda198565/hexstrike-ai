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

## Audit discipline

- Verify source, bytecode, and runtime behavior separately.
- Check proxy and implementation addresses independently.
- Validate findings with tests or simulation when possible.
- Label uncertain findings as hypotheses.

## Workflow discipline

- Start with a plan.
- Keep context small and relevant.
- Use fresh conversations for new audit targets.
- Deduplicate repeated findings.
- Do not modify more than three files without confirmation.

## Reporting discipline

- Use severity labels consistently.
- State impact in one sentence.
- State remediation in one sentence.
- Separate confirmed issues from assumptions.

## Immutable data (HexStrike)

- Live attack logs are read-only: `artifacts/workflow/traces/`, `attack_logs/`, `nuclei_steps/`.
- Write reports to `artifacts/web3-audit/` or `reports/` — never patch live campaign logs.
