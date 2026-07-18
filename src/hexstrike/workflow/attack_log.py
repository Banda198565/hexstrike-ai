"""Attack log parsing and normalization for skill-builder."""

from __future__ import annotations

from typing import Any


def is_attack_log(data: dict[str, Any]) -> bool:
    return "attack_id" in data and "result" in data and isinstance(data.get("steps"), list)


def is_campaign_trace(data: dict[str, Any]) -> bool:
    return "trace_id" in data or ("campaign_id" in data and "outcome" in data)


def is_skill_output(data: dict[str, Any]) -> bool:
    return "skill_name" in data and "input_schema" in data and isinstance(data.get("steps"), list)


def log_is_successful(data: dict[str, Any]) -> tuple[bool, str]:
    if is_attack_log(data):
        ok = bool((data.get("result") or {}).get("success"))
        return ok, data.get("attack_id", "unknown")
    if is_campaign_trace(data):
        ok = data.get("outcome") == "success"
        return ok, data.get("trace_id") or data.get("campaign_id", "unknown")
    return False, "unknown"


def log_source_id(data: dict[str, Any]) -> str:
    if is_attack_log(data):
        return str(data.get("attack_id", ""))
    return str(data.get("trace_id") or data.get("campaign_id") or "")


def skill_output_to_template(skill: dict[str, Any], *, source_id: str = "") -> dict[str, Any]:
    """Convert R1 SkillBuilderOutput JSON to internal workflow template for generators."""
    name = skill["skill_name"]
    in_schema = skill.get("input_schema") or {}
    props = in_schema.get("properties") or {}
    required = set(in_schema.get("required") or [])

    parameters = [
        {
            "name": k,
            "type": v.get("type", "string") if isinstance(v, dict) else "string",
            "required": k in required,
            "description": (v.get("description") or "") if isinstance(v, dict) else "",
        }
        for k, v in props.items()
    ]

    steps = []
    for s in skill.get("steps") or []:
        sid = s.get("id", s.get("step_id", 0))
        steps.append(
            {
                "step_id": sid,
                "skill_id": s.get("mcp_tool", s.get("skill_id", "unknown")),
                "phase": s.get("phase"),
                "depends_on": [sid - 1] if isinstance(sid, int) and sid > 1 else [],
                "input_template": s.get("inputs_from") or {},
                "expected_output": s.get("expected_output"),
                "next_step_condition": s.get("next_step_condition"),
                "rationale": s.get("description", ""),
            }
        )

    return {
        "workflow_id": name,
        "name": name.replace("_", " ").title(),
        "version": "1.0.0",
        "description": skill.get("description", ""),
        "tags": skill.get("tags") or [],
        "source_trace_id": skill.get("source_attack_id") or source_id,
        "parameters": parameters,
        "steps": steps,
        "mcp_tool": {
            "name": f"run_{name}",
            "description": skill.get("description", ""),
            "generate_stub": True,
        },
        "input_schema": in_schema,
        "output_schema": skill.get("output_schema") or {},
        "format": "skill_output_v1",
    }


def is_nuclei_step_log(data: dict[str, Any]) -> bool:
    """Standalone vuln_scan step log from Nuclei MCP."""
    if data.get("phase") != "vuln_scan":
        return False
    tool = data.get("mcp_tool") or data.get("tool")
    if tool not in ("nuclei_scan", "basic_scan", "nuclei"):
        return False
    output = data.get("output")
    return isinstance(output, dict) and "findings" in output


def is_nuclei_skill_output(data: dict[str, Any]) -> bool:
    return (
        "skill_name" in data
        and "input_schema" in data
        and "output_schema" in data
        and ("workflow_hint" in data or "interesting_findings" in data)
        and not isinstance(data.get("steps"), list)
    )


def nuclei_step_log_is_successful(data: dict[str, Any]) -> tuple[bool, str]:
    """Nuclei step succeeded when scan completed (findings may be empty)."""
    if not is_nuclei_step_log(data):
        return False, "unknown"
    output = data.get("output") or {}
    ok = data.get("status") == "success" or bool(output.get("success"))
    scan_id = str(output.get("scan_id") or data.get("step_id") or "unknown")
    return ok, scan_id


def nuclei_step_source_id(data: dict[str, Any]) -> str:
    output = data.get("output") or {}
    return str(output.get("scan_id") or data.get("step_id") or "unknown")


def nuclei_skill_output_to_template(skill: dict[str, Any], *, source_id: str = "") -> dict[str, Any]:
    """Convert R1 NucleiSkillBuilderOutput JSON to internal workflow template."""
    name = skill["skill_name"]
    in_schema = skill.get("input_schema") or {}
    props = in_schema.get("properties") or {}
    required = set(in_schema.get("required") or [])

    parameters = [
        {
            "name": k,
            "type": v.get("type", "string") if isinstance(v, dict) else "string",
            "required": k in required,
            "description": (v.get("description") or "") if isinstance(v, dict) else "",
        }
        for k, v in props.items()
    ]

    template_set = "{{template_set}}"
    severity = "{{severity_threshold}}"
    if isinstance(props.get("template_set"), dict) and props["template_set"].get("default"):
        template_set = str(props["template_set"]["default"])
    if isinstance(props.get("severity_threshold"), dict) and props["severity_threshold"].get("default"):
        severity = str(props["severity_threshold"]["default"])

    steps = [
        {
            "step_id": 1,
            "skill_id": "nuclei_scan",
            "phase": "vuln_scan",
            "depends_on": [],
            "input_template": {
                "target": "{{target_url}}",
                "tags": template_set,
                "severity": severity,
            },
            "expected_output": {
                "interesting_findings": "{{interesting_findings}}",
                "raw_report_path": "{{raw_report_path}}",
            },
            "rationale": skill.get("description", ""),
        }
    ]

    workflow_hint = skill.get("workflow_hint") or {}
    candidate_skills = workflow_hint.get("candidate_exploit_skills") or []
    for idx, exploit_skill in enumerate(candidate_skills, start=2):
        steps.append(
            {
                "step_id": idx,
                "skill_id": exploit_skill,
                "phase": workflow_hint.get("next_phase", "exploit"),
                "depends_on": [1],
                "input_template": {"target_url": "{{target_url}}", "from_findings": "{{interesting_findings}}"},
                "next_step_condition": "interesting_findings.length > 0",
                "rationale": f"Follow-up exploit skill suggested for findings ({exploit_skill})",
            }
        )

    return {
        "workflow_id": name,
        "name": name.replace("_", " ").title(),
        "version": "1.0.0",
        "description": skill.get("description", ""),
        "tags": skill.get("tags") or [],
        "source_trace_id": skill.get("source_scan_id") or source_id,
        "parameters": parameters,
        "steps": steps,
        "interesting_findings": skill.get("interesting_findings") or [],
        "workflow_hint": workflow_hint,
        "mcp_tool": {
            "name": f"run_{name}",
            "description": skill.get("description", ""),
            "generate_stub": True,
        },
        "input_schema": in_schema,
        "output_schema": skill.get("output_schema") or {},
        "format": "nuclei_skill_output_v1",
        "preconditions": [
            "Authorized scope for vulnerability scanning",
            "Nuclei MCP server available (nuclei_scan / basic_scan)",
        ],
        "postconditions": [
            "interesting_findings populated from real Nuclei output only",
            "raw_report_path points to JSONL artifact when scan produces output",
        ],
        "stop_conditions": [
            "Do not fabricate findings when Nuclei returns an empty set",
        ],
    }


def normalize_r1_payload(payload: dict[str, Any], *, source_id: str = "") -> dict[str, Any]:
    """Accept SkillBuilderOutput, NucleiSkillBuilderOutput, or legacy WorkflowTemplate from R1."""
    if is_nuclei_skill_output(payload):
        return nuclei_skill_output_to_template(payload, source_id=source_id)
    if is_skill_output(payload):
        return skill_output_to_template(payload, source_id=source_id)
    if "workflow_id" in payload:
        payload.setdefault("format", "workflow_template_v1")
        return payload
    raise ValueError("R1 payload is neither skill_output, nuclei_skill_output, nor workflow_template")
