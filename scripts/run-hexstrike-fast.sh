#!/usr/bin/env bash
# run-hexstrike-fast.sh — one-shot parallel P1–P7 fast pipeline
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export FIELD_RECON_INCREMENTAL="${FIELD_RECON_INCREMENTAL:-1}"
export FIELD_RECON_PARALLEL="${FIELD_RECON_PARALLEL:-4}"
export HOT_WATCH_DELTA="${HOT_WATCH_DELTA:-1}"
export PENTEST_FAST="${PENTEST_FAST:-1}"
export RESCUE_PREFETCH="${RESCUE_PREFETCH:-1}"

echo "=== HexStrike 7-pack FAST (parallel orchestrator) ==="
ARGS=(run hexstrike-7pack-fast)
[[ "${1:-}" == "--quiet" ]] && ARGS+=(--quiet)
python3 "$ROOT/scripts/hexstrike-orchestrator.py" "${ARGS[@]}"
python3 "$ROOT/scripts/docs/attack_map_diff.py"
echo "[OK] fast pipeline complete"
