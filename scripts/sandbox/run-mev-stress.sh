#!/usr/bin/env bash
# run-mev-stress.sh — hardcore MEV PnL stress suite
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "=== MEV STRESS: Python unit tests ==="
python3 -m unittest tests.mev_stress_test -v

echo ""
echo "=== MEV STRESS: Go classifier tests ==="
(cd cmd/agent && go test ./internal/mev/ -run 'Stress|PlanJIT|Sandwich|Backrun' -v -count=1)

echo ""
echo "=== MEV STRESS: fork zero-spread synthetic ==="
FORK_SYNTHETIC_ZERO_SPREAD=1 python3 scripts/sandbox/mev/fork_offensive.py | tail -8

echo ""
echo "=== MEV STRESS: JIT gas spike gate (classifier only) ==="
python3 - <<'PY'
import sys
sys.path.insert(0, "scripts/sandbox/mev")
from jit_engine import classify_jit_execution
m = classify_jit_execution(5*10**18, 500*10**18, 1000*10**18, gas_price_wei=10**12)
assert not m["should_execute"], m
print("[OK] JIT gas spike → skip:", m["skip_reason"])
PY

echo ""
echo "[OK] MEV stress suite PASS"
