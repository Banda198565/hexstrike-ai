#!/usr/bin/env python3
"""Attack map auto-diff — registry/workflows vs TARGET_ATTACK_MAP.md."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "docs" / "TARGET_ATTACK_MAP.md"
REG = ROOT / "agents" / "registry.json"
WF = ROOT / "agents" / "workflows.json"
OUT = ROOT / "artifacts" / "sandbox" / "attack-map-diff.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registry_tasks() -> set[str]:
    reg = load_json(REG)
    tasks: set[str] = set()
    for agent in reg.get("agents", {}).values():
        for task in agent.get("tasks", {}):
            tasks.add(task)
    return tasks


def workflow_names() -> set[str]:
    return set(load_json(WF).get("workflows", {}).keys())


def map_scripts() -> set[str]:
    if not MAP.is_file():
        return set()
    text = MAP.read_text(encoding="utf-8")
    return set(re.findall(r"`([a-zA-Z0-9_./-]+\.(?:py|sh))`", text))


def main() -> int:
    reg_tasks = registry_tasks()
    workflows = workflow_names()
    scripts = map_scripts()

    registry_outputs: set[str] = set()
    reg = load_json(REG)
    for agent in reg.get("agents", {}).values():
        for spec in agent.get("tasks", {}).values():
            if isinstance(spec, dict) and spec.get("output"):
                registry_outputs.add(spec["output"])

    missing_in_map = sorted(registry_outputs - {s for s in scripts if s.startswith("artifacts/")})
    extra_in_map = sorted(scripts - reg_tasks - workflows)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "map_path": str(MAP),
        "registry_task_count": len(reg_tasks),
        "workflow_count": len(workflows),
        "map_script_refs": len(scripts),
        "missing_in_map": missing_in_map[:30],
        "stale_map_refs": extra_in_map[:30],
        "fast_workflows": [w for w in sorted(workflows) if "parallel" in w or "fast" in w],
        "in_sync": not missing_in_map and not extra_in_map,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "output": str(OUT), "in_sync": payload["in_sync"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
