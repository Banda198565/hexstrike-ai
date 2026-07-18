#!/usr/bin/env python3
"""Unit tests for Nuclei skill-builder pipeline (no R1 / no nuclei binary)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.workflow.attack_log import (
    is_nuclei_skill_output,
    is_nuclei_step_log,
    nuclei_skill_output_to_template,
    nuclei_step_log_is_successful,
    normalize_r1_payload,
)
from hexstrike.workflow.generators import render_skill_md, write_artifacts
from hexstrike.workflow.skill_builder import SkillBuilder, build_nuclei_messages


def test_nuclei_step_log_detection() -> None:
    example = json.loads((ROOT / "config/workflow/nuclei-step-log.example.json").read_text())
    assert is_nuclei_step_log(example)
    ok, scan_id = nuclei_step_log_is_successful(example)
    assert ok, scan_id
    assert scan_id == "nuclei-20260718T192000Z-abc123"


def test_nuclei_skill_output_template() -> None:
    example = json.loads((ROOT / "config/workflow/nuclei-skill-output.example.json").read_text())
    assert is_nuclei_skill_output(example)
    template = nuclei_skill_output_to_template(example, source_id="test-scan")
    assert template["workflow_id"] == "nuclei_web_sqli_discovery"
    assert template["format"] == "nuclei_skill_output_v1"
    assert template["steps"][0]["skill_id"] == "nuclei_scan"
    assert len(template["interesting_findings"]) == 1
    assert template["workflow_hint"]["next_phase"] == "exploit"


def test_normalize_r1_payload_nuclei() -> None:
    example = json.loads((ROOT / "config/workflow/nuclei-skill-output.example.json").read_text())
    template = normalize_r1_payload(example, source_id="x")
    assert template["format"] == "nuclei_skill_output_v1"


def test_build_nuclei_messages() -> None:
    step = json.loads((ROOT / "config/workflow/nuclei-step-log.example.json").read_text())
    messages = build_nuclei_messages(step, skill_name_hint="nuclei_web_sqli_discovery")
    assert messages[0]["role"] == "system"
    assert "<NUCLEI_STEP_LOG_JSON>" in messages[1]["content"]
    assert "nuclei_web_sqli_discovery" in messages[1]["content"]


def test_render_nuclei_skill_md() -> None:
    example = json.loads((ROOT / "config/workflow/nuclei-skill-output.example.json").read_text())
    template = nuclei_skill_output_to_template(example)
    md = render_skill_md(template)
    assert "Interesting findings" in md
    assert "sqli_dump_users" in md
    assert "pentest_sql_injection_exploit" in md


def test_build_from_nuclei_skip_r1() -> None:
    step_path = ROOT / "config/workflow/nuclei-step-log.example.json"
    template_path = ROOT / "config/workflow/nuclei-skill-output.example.json"
    builder = SkillBuilder()
    result = builder.build_from_nuclei_step(
        step_path,
        skip_r1=True,
        template_override=json.loads(template_path.read_text()),
        dry_run=True,
    )
    assert result["ok"]
    assert result["template"]["workflow_id"] == "nuclei_web_sqli_discovery"


def main() -> int:
    tests = [
        test_nuclei_step_log_detection,
        test_nuclei_skill_output_template,
        test_normalize_r1_payload_nuclei,
        test_build_nuclei_messages,
        test_render_nuclei_skill_md,
        test_build_from_nuclei_skip_r1,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
