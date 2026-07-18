"""Skill-builder pipeline: campaign trace → R1 → workflow template → SKILL.md + MCP stub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hexstrike.workflow.generators import write_artifacts
from hexstrike.workflow.r1_client import R1Client, extract_json
from hexstrike.workflow.registry_update import register_workflow_in_catalog
from hexstrike.workflow.trace_logger import CampaignTrace

_REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = _REPO_ROOT / "config" / "skill-builder-prompt.md"
OUTPUT_DIR = _REPO_ROOT / "artifacts" / "workflow" / "built"


def load_skill_builder_prompt() -> str:
    if PROMPT_PATH.is_file():
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Generate a parameterized WorkflowTemplate JSON from the campaign trace."


def build_messages(trace: CampaignTrace | dict[str, Any], skill_name_hint: str | None = None) -> list[dict[str, str]]:
    trace_dict = trace.to_dict() if isinstance(trace, CampaignTrace) else trace
    user_extra = ""
    if skill_name_hint:
        user_extra = f"\nPrefer workflow_id hint: `{skill_name_hint}`"
    return [
        {"role": "system", "content": load_skill_builder_prompt()},
        {
            "role": "user",
            "content": (
                "Generalize this successful campaign trace into a WorkflowTemplate JSON.\n"
                f"{user_extra}\n\n"
                f"{json.dumps(trace_dict, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


class SkillBuilder:
    """log → R1 → template → SKILL.md + MCP stub + catalog entry."""

    def __init__(self, r1: R1Client | None = None) -> None:
        self.r1 = r1 or R1Client()

    def analyze_trace(
        self,
        trace: CampaignTrace | dict[str, Any] | Path | str,
        *,
        skill_name_hint: str | None = None,
        dry_run_r1: bool = False,
    ) -> dict[str, Any]:
        if isinstance(trace, (Path, str)):
            trace_obj = CampaignTrace.from_dict(json.loads(Path(trace).read_text(encoding="utf-8")))
        elif isinstance(trace, CampaignTrace):
            trace_obj = trace
        else:
            trace_obj = CampaignTrace.from_dict(trace)

        if trace_obj.outcome != "success":
            return {
                "ok": False,
                "error": f"Trace outcome is '{trace_obj.outcome}' — skill-builder runs on success only",
                "trace_id": trace_obj.trace_id,
            }

        messages = build_messages(trace_obj, skill_name_hint)

        if dry_run_r1:
            return {
                "ok": True,
                "dry_run_r1": True,
                "trace_id": trace_obj.trace_id,
                "messages_preview": messages[1]["content"][:500],
            }

        llm = self.r1.chat(messages, temperature=0.2)
        if not llm.get("ok"):
            return {"ok": False, "error": llm.get("error"), "trace_id": trace_obj.trace_id}

        try:
            template = extract_json(llm["content"])
        except (json.JSONDecodeError, ValueError) as exc:
            return {
                "ok": False,
                "error": f"Failed to parse workflow template: {exc}",
                "raw_content": (llm.get("content") or "")[:2000],
                "trace_id": trace_obj.trace_id,
            }

        template.setdefault("source_trace_id", trace_obj.trace_id)
        return {"ok": True, "trace_id": trace_obj.trace_id, "template": template, "llm": llm}

    def build_from_trace(
        self,
        trace: CampaignTrace | dict[str, Any] | Path | str,
        *,
        skill_name_hint: str | None = None,
        dry_run: bool = False,
        skip_r1: bool = False,
        template_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Full pipeline: R1 analyze → write files → update catalog."""
        if skip_r1 and template_override:
            template = template_override
            analysis = {"ok": True, "trace_id": template.get("source_trace_id"), "template": template}
        else:
            analysis = self.analyze_trace(trace, skill_name_hint=skill_name_hint, dry_run_r1=dry_run)
            if not analysis.get("ok"):
                return analysis
            if dry_run:
                return analysis
            template = analysis["template"]

        written = write_artifacts(template, dry_run=dry_run)
        registry = register_workflow_in_catalog(template, dry_run=dry_run)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = OUTPUT_DIR / f"{template['workflow_id']}-build-report.json"
        report = {
            "trace_id": analysis.get("trace_id"),
            "workflow_id": template.get("workflow_id"),
            "written": written,
            "registry": registry,
        }
        if not dry_run:
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["report_path"] = str(report_path)
        report["ok"] = True
        report["template"] = template
        return report

    def process_pending(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Process all successful traces flagged in pending_skillify.json."""
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

        results = []
        for p in paths:
            results.append(self.build_from_trace(p, dry_run=dry_run))
        if not dry_run and results:
            pending_path.unlink(missing_ok=True)
        return results
