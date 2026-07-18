"""Load and validate HexStrike MCP skill catalog for Reasoning-Master."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = _REPO_ROOT / "config" / "skills" / "catalog.json"
SCHEMAS_DIR = _REPO_ROOT / "config" / "skills" / "schemas"
MASTER_SCHEMA_PATH = _REPO_ROOT / "config" / "reasoning-master.schema.json"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or CATALOG_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def get_skill(skill_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cat = catalog or load_catalog()
    return cat.get("skills", {}).get(skill_id)


def list_skills(*, layer: str | None = None, catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cat = catalog or load_catalog()
    out: list[dict[str, Any]] = []
    for sid, meta in cat.get("skills", {}).items():
        if layer and meta.get("layer") != layer:
            continue
        out.append({"skill_id": sid, **meta})
    return out


def load_skill_schema(skill_id: str, direction: str = "input", catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load input or output JSON schema for a skill."""
    meta = get_skill(skill_id, catalog)
    if not meta:
        raise KeyError(f"Unknown skill: {skill_id}")
    key = f"{direction}_schema"
    rel = meta.get(key)
    if not rel:
        raise ValueError(f"Skill {skill_id} has no {key}")
    path = _REPO_ROOT / rel
    return json.loads(path.read_text(encoding="utf-8"))


def skills_for_task(task: dict[str, Any], catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Resolve full skill metadata for a Reasoning-Master task."""
    cat = catalog or load_catalog()
    resolved: list[dict[str, Any]] = []
    for ref in task.get("skills") or []:
        sid = ref.get("skill_id")
        base = get_skill(sid, cat)
        if not base:
            resolved.append({"skill_id": sid, "error": "not_in_catalog"})
            continue
        resolved.append({**base, **ref, "skill_id": sid})
    return resolved


def validate_plan_skills(plan: dict[str, Any], allowed_ids: set[str]) -> list[str]:
    """Ensure every plan step references an allowed skill_id."""
    issues: list[str] = []
    for step in plan.get("steps") or []:
        sid = step.get("skill_id")
        if sid not in allowed_ids:
            issues.append(f"step {step.get('step_id')}: skill_id '{sid}' not in task.skills")
    return issues
