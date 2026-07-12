#!/usr/bin/env bash
# run-mev-live-stress.sh — production-hardening live pipeline stress (read-only)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SANDBOX="$ROOT/scripts/sandbox"

echo "=== LIVE STRESS: Python unit tests ==="
python3 -m unittest tests.mev_live_stress_test tests.mev_fork_stress_test -v

echo ""
echo "=== LIVE STRESS: Go builder classifier ==="
(cd cmd/agent && go test ./internal/mev/ -run 'Builder' -v -count=1)

echo ""
echo "=== LIVE STRESS: live mempool ingest (read-only) ==="
env -u MEV_RPC_URL MEV_SANDBOX_ONLY=1 python3 "$SANDBOX/mev/mempool_live.py"

echo ""
echo "=== LIVE STRESS: full offensive pipeline ==="
MEV_SANDBOX_ONLY=1 BUILDER_SIM_ONLY=1 PIPELINE_USE_FORK=1 \
  python3 "$SANDBOX/mev/offensive_pipeline.py"

echo ""
echo "=== LIVE STRESS: assert artifacts ==="
python3 - <<'PY'
import json
from pathlib import Path
art = Path("artifacts/sandbox")
for name in (
    "mev-live-mempool-scan.json",
    "mev-bsc-fork-result.json",
    "mev-builder-sim.json",
    "mev-live-pipeline-result.json",
):
    p = art / name
    assert p.is_file(), f"missing {name}"
    json.load(open(p))
    print(f"[OK] {name}")
assert json.load(open(art / "mev-builder-sim.json"))["would_submit"] is False
print("[OK] builder dry-run (no submit)")
PY

echo ""
echo "[OK] MEV live stress PASS"
