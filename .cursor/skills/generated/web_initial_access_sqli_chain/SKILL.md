---
name: web_initial_access_sqli_chain
description: Auto-generated from campaign trace atk-2026-07-18-001. Use for Web Initial Access Sqli Chain workflows in HexStrike orchestrator. Invoke via MCP tool `run_web_initial_access_sqli_chain`.
---

# Web Initial Access Sqli Chain

Recon → HTTP vuln scan → SQLi exploit → admin session — parameterized web initial access chain

**Version:** 1.0.0  
**Tags:** web, initial_access, sql_injection, chain

## Parameters

- `target_url` (string) *required*: Base URL of target web application, e.g. https://example.com
- `target_ip` (string): Target IP if known
- `scan_profile` (string): Port/service scan profile
- `dbms_type` (string): DBMS type (mysql, postgres, ...)

## Preconditions

- See authorization scope

## Steps

1. **pentest_nmap_scan** (recon) — Port and service scan
   ```json
{
  "skill_input": [
    "target_ip",
    "scan_profile"
  ]
}
   ```
   Condition: if HTTP/HTTPS found → step 2; else success=false
2. **pentest_http_vuln_scan** (vuln_scan) — HTTP vulnerability scan for SQLi
   ```json
{
  "skill_input": [
    "target_url"
  ],
  "previous_step_output": [
    "services"
  ]
}
   ```
   Condition: if SQLi found → step 3
3. **pentest_sql_injection_exploit** (exploit) — Exploit SQLi to extract users table
   ```json
{
  "skill_input": [
    "dbms_type",
    "target_url"
  ],
  "previous_step_output": [
    "findings"
  ]
}
   ```
   Condition: if users extracted → step 4
4. **pentest_web_session_hijack** (post_exploitation) — Obtain privileged web session from extracted creds
   ```json
{
  "previous_step_output": [
    "extracted_data"
  ]
}
   ```
   Condition: finish success=true impact=initial_access_admin_web

## Postconditions



## Stop conditions



## Checklist



## Pitfalls


