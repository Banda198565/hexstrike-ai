---
name: web_initial_access_chain
description: Auto-generated from campaign trace trace-web-chain-20260718-001. Use for Web Initial Access Chain workflows in HexStrike orchestrator. Invoke via MCP tool `run_web_initial_access_chain`.
---

# Web Initial Access Chain

Recon → nuclei/Jenkins CVE → sandbox initial access → local privesc enumeration

**Version:** 1.0.0  
**Tags:** pentest, web, jenkins

## Parameters

- `target_host` (string) *required*: Lab target hostname or IP
- `authorization_ref` (string) *required*: Signed scope reference
- `jenkins_port` (integer): HTTP port for Jenkins

## Preconditions

- authorization_ref valid
- target in lab scope
- HEXSTRIKE_SANDBOX=1 for exploit steps

## Steps

1. **pentest_recon** — Map attack surface before exploitation
   ```json
{
  "targets": [
    {
      "host": "{{target_host}}",
      "ports": "top-1000"
    }
  ],
  "tools": [
    "nmap",
    "httpx",
    "nuclei"
  ],
  "authorization_ref": "{{authorization_ref}}"
}
   ```
2. **exploit_chain_builder** — Select MITRE-aligned chain from recon
   ```json
{
  "recon_ref": "{{step_1.artifact_ref}}",
  "framework": "mitre_attack",
  "sandbox_only": true
}
   ```

## Postconditions

- initial access artifact recorded
- session ref in credential_session vault

## Stop conditions

- critical finding without sandbox
- authorization expired

## Checklist

- [ ] Confirm authorization_ref
- [ ] Run recon first
- [ ] Store shell session via credential_session

## Pitfalls

- Do not run exploit steps without sandbox
- Rotate session refs after campaign
