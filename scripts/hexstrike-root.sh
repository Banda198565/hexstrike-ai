#!/usr/bin/env bash
# Resolve canonical HexStrike install (prefers /opt/hexstrike-ai, falls back to /data/pentest/hexstrike).
# Usage: source scripts/hexstrike-root.sh && cd "$HEXSTRIKE_ROOT"
set -euo pipefail

_candidates=(
  "${HEXSTRIKE_DIR:-}"
  "/opt/hexstrike-ai"
  "/data/pentest/hexstrike"
  "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
)

HEXSTRIKE_ROOT=""
for d in "${_candidates[@]}"; do
  [[ -n "$d" && -f "$d/hexstrike_orchestrator.py" ]] || continue
  HEXSTRIKE_ROOT="$d"
  break
done

if [[ -z "$HEXSTRIKE_ROOT" ]]; then
  echo "hexstrike-root: no install found (checked /opt/hexstrike-ai, /data/pentest/hexstrike)" >&2
  exit 1
fi

export HEXSTRIKE_ROOT
