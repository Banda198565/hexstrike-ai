"""Update config/skills/catalog.json with generated workflow skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = _REPO_ROOT / "config" / "skills" / "catalog.json"


def register_workflow_in_catalog(
    template: dict[str, Any],
    *,
    catalog_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add or update skill entry derived from workflow template."""
    path = catalog_path or CATALOG_PATH
    catalog = json.loads(path.read_text(encoding="utf-8"))
    wid = template["workflow_id"]
    mcp_name = (template.get("mcp_tool") or {}).get("name") or f"run_{wid}"

    rel_schema_in = f"config/skills/schemas/generated/{wid}.input.json"
    rel_schema_out = f"config/skills/schemas/generated/{wid}.output.json"

    entry: dict[str, Any] = {
        "version": template.get("version", "1.0.0"),
        "layer": "generated",
        "description": template.get("description") or template.get("name", wid),
        "input_schema": rel_schema_in,
        "output_schema": rel_schema_out,
        "mcp_tool": mcp_name,
        "source_trace_id": template.get("source_trace_id"),
        "auto_generated": True,
        "parallelizable": False,
        "constraints": template.get("tags") or [],
        "workflow_steps": len(template.get("steps") or []),
    }

    catalog.setdefault("skills", {})[wid] = entry

    if dry_run:
        return {"skill_id": wid, "catalog_entry": entry, "dry_run": True}

    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    schema_dir = _REPO_ROOT / "config" / "skills" / "schemas" / "generated"
    schema_dir.mkdir(parents=True, exist_ok=True)

    params = template.get("parameters") or []
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{wid}.input",
        "type": "object",
        "required": [p["name"] for p in params if p.get("required", True)],
        "properties": {
            p["name"]: {"type": p.get("type", "string"), "description": p.get("description", "")}
            for p in params
        },
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{wid}.output",
        "type": "object",
        "required": ["workflow_id", "status"],
        "properties": {
            "workflow_id": {"type": "string"},
            "status": {"type": "string"},
            "steps_completed": {"type": "integer"},
            "artifacts": {"type": "array", "items": {"type": "string"}},
        },
    }
    (schema_dir / f"{wid}.input.json").write_text(json.dumps(input_schema, indent=2) + "\n", encoding="utf-8")
    (schema_dir / f"{wid}.output.json").write_text(json.dumps(output_schema, indent=2) + "\n", encoding="utf-8")

    return {"skill_id": wid, "catalog_path": str(path), "input_schema": rel_schema_in, "output_schema": rel_schema_out}
