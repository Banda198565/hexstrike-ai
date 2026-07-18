#!/usr/bin/env python3
"""Skill-builder CLI — campaign trace → R1 → SKILL.md + MCP tool + catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.workflow.skill_builder import SkillBuilder
from hexstrike.workflow.trace_logger import CampaignTraceLogger


def cmd_build(args: argparse.Namespace) -> int:
    builder = SkillBuilder()
    result = builder.build_from_trace(
        args.trace,
        skill_name_hint=args.name_hint,
        dry_run=args.dry_run,
        skip_r1=args.skip_r1,
        template_override=json.loads(Path(args.template).read_text()) if args.template else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    builder = SkillBuilder()
    result = builder.analyze_trace(args.trace, skill_name_hint=args.name_hint, dry_run_r1=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_pending(args: argparse.Namespace) -> int:
    builder = SkillBuilder()
    results = builder.process_pending(dry_run=args.dry_run)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(r.get("ok") for r in results) else 1


def cmd_demo_attack_log(args: argparse.Namespace) -> int:
    example = ROOT / "config" / "workflow" / "attack-log.example.json"
    if not example.is_file():
        print(json.dumps({"ok": False, "error": f"Missing {example}"}))
        return 1
    data = json.loads(example.read_text(encoding="utf-8"))
    out_dir = ROOT / "artifacts" / "workflow" / "attack_logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{data['attack_id']}.json"
    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_path)}))
    return 0


def cmd_demo_trace(args: argparse.Namespace) -> int:
    """Record a demo trace from example JSON (no live hooks)."""
    example = ROOT / "config" / "workflow" / "campaign-trace.example.json"
    if not example.is_file():
        print(json.dumps({"ok": False, "error": f"Missing {example}"}))
        return 1
    data = json.loads(example.read_text(encoding="utf-8"))
    out_dir = ROOT / "artifacts" / "workflow" / "traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{data['trace_id']}.json"
    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_path)}))
    return 0


def cmd_demo_nuclei_step(args: argparse.Namespace) -> int:
    example = ROOT / "config" / "workflow" / "nuclei-step-log.example.json"
    if not example.is_file():
        print(json.dumps({"ok": False, "error": f"Missing {example}"}))
        return 1
    data = json.loads(example.read_text(encoding="utf-8"))
    out_dir = ROOT / "artifacts" / "workflow" / "nuclei_steps"
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_id = (data.get("output") or {}).get("scan_id", "nuclei-step")
    out_path = out_dir / f"{scan_id}.json"
    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_path)}))
    return 0


def cmd_build_nuclei(args: argparse.Namespace) -> int:
    builder = SkillBuilder()
    result = builder.build_from_nuclei_step(
        args.step_log,
        skill_name_hint=args.name_hint,
        dry_run=args.dry_run,
        skip_r1=args.skip_r1,
        template_override=json.loads(Path(args.template).read_text()) if args.template else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_analyze_nuclei(args: argparse.Namespace) -> int:
    builder = SkillBuilder()
    result = builder.analyze_nuclei_step(args.step_log, skill_name_hint=args.name_hint, dry_run_r1=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="HexStrike skill-builder workflow engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Full pipeline: trace → R1 → artifacts")
    p_build.add_argument("trace", help="Path to campaign trace JSON")
    p_build.add_argument("--name-hint", default=None)
    p_build.add_argument("--dry-run", action="store_true")
    p_build.add_argument("--skip-r1", action="store_true", help="Use --template instead of R1")
    p_build.add_argument("--template", default=None, help="Workflow template JSON (with --skip-r1)")
    p_build.set_defaults(func=cmd_build)

    p_analyze = sub.add_parser("analyze", help="R1 only — return workflow template JSON")
    p_analyze.add_argument("trace", help="Path to campaign trace JSON")
    p_analyze.add_argument("--name-hint", default=None)
    p_analyze.add_argument("--dry-run", action="store_true", help="Preview prompt without R1 call")
    p_analyze.set_defaults(func=cmd_analyze)

    p_pending = sub.add_parser("pending", help="Process pending_skillify.json queue")
    p_pending.add_argument("--dry-run", action="store_true")
    p_pending.set_defaults(func=cmd_pending)

    p_demo = sub.add_parser("demo-trace", help="Copy example attack log to artifacts/")
    p_demo.set_defaults(func=cmd_demo_trace)

    p_demo2 = sub.add_parser("demo-attack-log", help="Copy attack-log.example.json to artifacts/")
    p_demo2.set_defaults(func=cmd_demo_attack_log)

    p_demo_nuclei = sub.add_parser("demo-nuclei-step", help="Copy nuclei-step-log.example.json to artifacts/")
    p_demo_nuclei.set_defaults(func=cmd_demo_nuclei_step)

    p_build_nuclei = sub.add_parser("build-nuclei", help="Nuclei step log → R1 → MCP skill artifacts")
    p_build_nuclei.add_argument("step_log", help="Path to vuln_scan step JSON")
    p_build_nuclei.add_argument("--name-hint", default=None)
    p_build_nuclei.add_argument("--dry-run", action="store_true")
    p_build_nuclei.add_argument("--skip-r1", action="store_true", help="Use --template instead of R1")
    p_build_nuclei.add_argument("--template", default=None, help="Nuclei skill output JSON (with --skip-r1)")
    p_build_nuclei.set_defaults(func=cmd_build_nuclei)

    p_analyze_nuclei = sub.add_parser("analyze-nuclei", help="R1 only — interpret Nuclei step log")
    p_analyze_nuclei.add_argument("step_log", help="Path to vuln_scan step JSON")
    p_analyze_nuclei.add_argument("--name-hint", default=None)
    p_analyze_nuclei.add_argument("--dry-run", action="store_true", help="Preview prompt without R1 call")
    p_analyze_nuclei.set_defaults(func=cmd_analyze_nuclei)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
