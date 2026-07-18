---
name: nuclei_web_sqli_discovery
description: Auto-generated from campaign trace nuclei-20260718T192000Z-abc123. Use for Nuclei Web Sqli Discovery workflows in HexStrike orchestrator. Invoke via MCP tool `run_nuclei_web_sqli_discovery`.
---

# Nuclei Web Sqli Discovery

Nuclei-based discovery and classification of SQL injection findings for web targets

**Version:** 1.0.0  
**Tags:** nuclei, web, sql_injection, vuln_scan

## Interesting findings (from source scan)

- **SQL Injection** (high) — `sqli_dump_users`

## Workflow hint

- **Next phase:** exploit
- **Candidate exploit skills:** `pentest_sql_injection_exploit`, `pentest_web_session_hijack`

## Parameters

- `target_url` (string) *required*: Base URL of web target, e.g. https://example.com
- `template_set` (string): Nuclei tags or template set
- `severity_threshold` (string): Minimum severity for interesting findings

## Preconditions

- Authorized scope for vulnerability scanning
- Nuclei MCP server available (nuclei_scan / basic_scan)

## Steps

1. **nuclei_scan** (vuln_scan) — Nuclei-based discovery and classification of SQL injection findings for web targets
   ```json
{
  "target": "{{target_url}}",
  "tags": "cve,sqli",
  "severity": "high"
}
   ```
2. **pentest_sql_injection_exploit** (exploit) — Follow-up exploit skill suggested for findings (pentest_sql_injection_exploit)
   ```json
{
  "target_url": "{{target_url}}",
  "from_findings": "{{interesting_findings}}"
}
   ```
   Condition: interesting_findings.length > 0
3. **pentest_web_session_hijack** (exploit) — Follow-up exploit skill suggested for findings (pentest_web_session_hijack)
   ```json
{
  "target_url": "{{target_url}}",
  "from_findings": "{{interesting_findings}}"
}
   ```
   Condition: interesting_findings.length > 0

## Postconditions

- interesting_findings populated from real Nuclei output only
- raw_report_path points to JSONL artifact when scan produces output

## Stop conditions

- Do not fabricate findings when Nuclei returns an empty set

## Checklist



## Pitfalls


