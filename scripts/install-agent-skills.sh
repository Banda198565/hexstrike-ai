#!/usr/bin/env bash
# Install addyosmani/agent-skills into Cursor project context.
# Upstream: https://github.com/addyosmani/agent-skills
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Installing agent-skills for Cursor"
if command -v npx >/dev/null 2>&1; then
  npx --yes skills add addyosmani/agent-skills --agent cursor
else
  echo "npx not found; clone upstream manually and sync into .cursor/skills/"
  exit 1
fi

mkdir -p .cursor/skills
if command -v rsync >/dev/null 2>&1; then
  rsync -a .agents/skills/ .cursor/skills/
else
  cp -a .agents/skills/. .cursor/skills/
fi

RULE_FILE=".cursor/rules/agent-skills.mdc"
if [[ ! -f "$RULE_FILE" ]]; then
  echo "Warning: $RULE_FILE missing — create routing rule per docs/cursor-setup.md"
fi

echo "==> Installed $(find .cursor/skills -name SKILL.md | wc -l | tr -d ' ') skills under .cursor/skills/"
echo "Done. Commit .cursor/skills/, .cursor/rules/, skills-lock.json for team sharing."
