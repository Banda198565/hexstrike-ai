"""Skill-builder pipeline: attack log → R1 → skill JSON → SKILL.md + MCP stub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hexstrike.workflow.attack_log import (
    is_skill_output,
    log_is_successful,
    log_source_id,
    normalize_r1_payload,
)
from hexstrike.workflow.generators import write_artifacts
from hexstrike.workflow.r1_client import R1Client, extract_json
from hexstrike.workflow.registry_update import register_workflow_in_catalog
from hexstrike.workflow.trace_logger import CampaignTrace

_REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = _REPO_ROOT / "config" / "skill-builder-prompt.md"
OUTPUT_DIR = _REPO_ROOT / "artifacts" / "workflow" / "built"
ATTACK_LOG_PLACEHOLDER = "<ATTACK_LOG_JSON>"


def load_skill_builder_prompt() -> str:
    if PROMPT_PATH.is_file():
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Generate parameterized MCP skill JSON from the attack log."


def _load_log_data(source: CampaignTrace | dict[str, Any] | Path | str) -> dict[str, Any]:
    if isinstance(source, (Path, str)):
        return json.loads(Path(source).read_text(encoding="utf-8"))
    if isinstance(source, CampaignTrace):
        return source.to_dict()
    return source


def build_messages(
    log_data: dict[str, Any],
    *,
    skill_name_hint: str | None = None,
) -> list[dict[str, str]]:
    system = load_skill_builder_prompt()
    log_json = json.dumps(log_data, ensure_ascii=False, indent=2)

    user_body = (
        "Проанализируй лог атаки и верни JSON skill по схеме из system prompt.\n"
    )
    if skill_name_hint:
        user_body += f"Подсказка для skill_name: `{skill_name_hint}`\n\n"
    user_body += f"<ATTACK_LOG_JSON>\n{log_json}\n</ATTACK_LOG_JSON>"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_body},
    ]


class SkillBuilder:
    """attack_log.json → R1 → skill JSON → SKILL.md + MCP stub + catalog."""

    def __init__(self, r1: R1Client | None = None) -> None:
        self.r1 = r1 or R1Client()

    def analyze_trace(
        self,
        source: CampaignTrace | dict[str, Any] | Path | str,
        *,
        skill_name_hint: str | None = None,
        dry_run_r1: bool = False,
    ) -> dict[str, Any]:
        log_data = _load_log_data(source)
        ok, log_id = log_is_successful(log_data)
        if not ok:
            return {
                "ok": False,
                "error": "Skill-builder runs on successful attacks only (result.success=true or outcome=success)",
                "log_id": log_id,
            }

        messages = build_messages(log_data, skill_name_hint=skill_name_hint)

        if dry_run_r1:
            return {
                "ok": True,
                "dry_run_r1": True,
                "log_id": log_id,
                "messages_preview": messages[1]["content"][:800],
            }

        llm = self.r1.chat(messages, temperature=0.2)
        if not llm.get("ok"):
            return {"ok": False, "error": llm.get("error"), "log_id": log_id}

        try:
            raw = extract_json(llm["content"])
            if is_skill_output(raw):
                template = normalize_r1_payload(raw, source_id=log_source_id(log_data))
            else:
                template = normalize_r1_payload(raw, source_id=log_source_id(log_data))
        except (json.JSONDecodeError, ValueError) as exc:
            return {
                "ok": False,
                "error": f"Failed to parse R1 skill JSON: {exc}",
                "raw_content": (llm.get("content") or "")[:2000],
                "log_id": log_id,
            }

        return {
            "ok": True,
            "log_id": log_id,
            "skill": raw if is_skill_output(raw) else None,
            "template": template,
            "llm": llm,
        }

    def build_from_trace(
        self,
        source: CampaignTrace | dict[str, Any] | Path | str,
        *,
        skill_name_hint: str | None = None,
        dry_run: bool = False,
        skip_r1: bool = False,
        template_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log_data = _load_log_data(source)
        log_id = log_source_id(log_data)

        if skip_r1 and template_override:
            if is_skill_output(template_override):
                template = normalize_r1_payload(template_override, source_id=log_id)
                raw_skill = template_override
            else:
                template = normalize_r1_payload(template_override, source_id=log_id)
                raw_skill = None
            analysis = {"ok": True, "log_id": log_id, "template": template, "skill": raw_skill}
        else:
            analysis = self.analyze_trace(source, skill_name_hint=skill_name_hint, dry_run_r1=dry_run)
            if not analysis.get("ok"):
                return analysis
            if dry_run:
                return analysis
            template = analysis["template"]

        written = write_artifacts(template, dry_run=dry_run)
        registry = register_workflow_in_catalog(template, dry_run=dry_run)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report = {
            "log_id": log_id,
            "workflow_id": template.get("workflow_id"),
            "format": template.get("format"),
            "written": written,
            "registry": registry,
        }
        if not dry_run:
            report_path = OUTPUT_DIR / f"{template['workflow_id']}-build-report.json"
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            report["report_path"] = str(report_path)
            skill_json_path = Path(written.get("skill_md", "")).parent / "skill.json"
            if analysis.get("skill") and skill_json_path.parent.exists():
                skill_json_path.write_text(
                    json.dumps(analysis["skill"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                report["skill_json"] = str(skill_json_path)
        report["ok"] = True
        report["template"] = template
        return report

    def process_pending(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        from hexstrike.workflow.trace_logger import TRACE_DIR

        pending_path = TRACE_DIR / "pending_skillify.json"
        if not pending_path.is_file():
            return []
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        paths: list[str] = []
        if isinstance(pending, dict) and pending.get("path"):
            paths = [pending["path"]]
        elif isinstance(pending, list):
            paths = [p.get("path") for p in pending if p.get("path")]

        results = [self.build_from_trace(p, dry_run=dry_run) for p in paths]
        if not dry_run and results:
            pending_path.unlink(missing_ok=True)
        return results
