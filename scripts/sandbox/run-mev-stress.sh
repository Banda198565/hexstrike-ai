#!/usr/bin/env bash
# run-mev-stress.sh — hardcore MEV PnL + Anvil e2e stress suite (Variant C)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SANDBOX="$ROOT/scripts/sandbox"
RPC="http://127.0.0.1:${ANVIL_PORT:-8545}"
ART="$ROOT/artifacts/sandbox"
REPORT="$ART/mev-stress-report.json"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "[FAIL] missing: $1"; exit 1; }
}

wait_for_rpc() {
  local url="$1" tries="${2:-30}"
  for ((i = 1; i <= tries; i++)); do
    if curl -sf --max-time 2 "$url" \
      -X POST -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "[FAIL] RPC not ready: $url"
  return 1
}

# ── Phase A: classifier / unit stress (offline) ─────────────────────────────
run_unit_stress() {
  echo "=== MEV STRESS A: Python unit tests ==="
  python3 -m unittest tests.mev_stress_test tests.mev_e2e_assert_test -v

  echo ""
  echo "=== MEV STRESS A: Go classifier tests ==="
  (cd cmd/agent && go test ./internal/mev/ -run 'Stress|PlanJIT|Sandwich|Backrun' -v -count=1)

  echo ""
  echo "=== MEV STRESS A: fork zero-spread synthetic ==="
  FORK_SYNTHETIC_ZERO_SPREAD=1 python3 scripts/sandbox/mev/fork_offensive.py | tail -8

  echo ""
  echo "=== MEV STRESS A: JIT gas spike gate (classifier only) ==="
  python3 - <<'PY'
import sys
sys.path.insert(0, "scripts/sandbox/mev")
from jit_engine import classify_jit_execution
m = classify_jit_execution(5*10**18, 500*10**18, 1000*10**18, gas_price_wei=10**12)
assert not m["should_execute"], m
print("[OK] JIT gas spike → skip:", m["skip_reason"])
PY
}

# ── Phase C: live Anvil e2e (plan → tx → artifacts) ─────────────────────────
run_anvil_e2e() {
  echo ""
  echo "=== MEV STRESS C: Anvil e2e — prerequisites ==="
  require_cmd anvil
  require_cmd cast
  require_cmd forge
  require_cmd python3
  require_cmd curl

  echo ""
  echo "=== MEV STRESS C: fresh Anvil (chain 31337) ==="
  bash "$SANDBOX/stop-anvil.sh" 2>/dev/null || true
  sleep 2
  bash "$SANDBOX/start-anvil.sh"
  wait_for_rpc "$RPC"
  bash "$SANDBOX/setup-anvil-env.sh" 2>/dev/null || true
  forge build --root "$SANDBOX/contracts" >/dev/null

  mkdir -p "$ART"
  : >"$ART/redteam-report.json"
  python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("artifacts/sandbox/redteam-report.json")
p.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "runs": []}, indent=2) + "\n")
PY

  export MEV_RPC_URL="$RPC" MEV_SANDBOX_ONLY=1 MEV_ALLOWED_CHAINS=31337

  echo ""
  echo "=== MEV STRESS C: full agent pipeline (mempool → sandwich → JIT → backrun) ==="
  python3 "$SANDBOX/mev/mempool_scanner.py"
  python3 "$SANDBOX/mev/sandwich_engine.py"
  JIT_FORCE_DEMO=1 python3 "$SANDBOX/mev/jit_engine.py"
  python3 "$SANDBOX/mev/backrun_engine.py"

  echo ""
  echo "=== MEV STRESS C: assert full-stack artifacts ==="
  python3 "$SANDBOX/mev/mev_e2e_assert.py" --mode full-stack --report "$REPORT"

  echo ""
  echo "=== MEV STRESS C: JIT skip gate (live engine, no FORCE_DEMO) ==="
  JIT_FORCE_DEMO=0 JIT_GAS_PRICE_WEI=1000000000000 JIT_VICTIM_WEI=1000000000000000 \
    python3 "$SANDBOX/mev/jit_engine.py" || true
  python3 - <<'PY'
import json
from pathlib import Path
src = Path("artifacts/sandbox/mev-jit-result.json")
dst = Path("artifacts/sandbox/mev-jit-skip-gate.json")
if src.is_file():
    dst.write_text(src.read_text())
PY
  python3 "$SANDBOX/mev/mev_e2e_assert.py" --mode jit-skip-gate --report "$REPORT"

  echo ""
  echo "=== MEV STRESS C: redteam attacks 08–11 (same Anvil session) ==="
  bash "$SANDBOX/redteam/08-mev-sandwich-sim.sh"
  bash "$SANDBOX/redteam/09-mev-frontrun-gas-race.sh"
  bash "$SANDBOX/redteam/10-mev-jit-liquidity.sh"
  bash "$SANDBOX/redteam/11-mev-backrun-arb.sh"

  echo ""
  echo "=== MEV STRESS C: assert redteam outcomes ==="
  python3 "$SANDBOX/mev/mev_e2e_assert.py" --mode redteam --report "$REPORT"

  echo ""
  echo "=== MEV STRESS C: unified e2e report ==="
  python3 "$SANDBOX/mev/mev_e2e_assert.py" --mode all --report "$REPORT"
  echo "[OK] report → $REPORT"
}

# ── main ──────────────────────────────────────────────────────────────────────
if [[ "${MEV_STRESS_SKIP_UNIT:-0}" != "1" ]]; then
  run_unit_stress
else
  echo "[SKIP] unit stress (MEV_STRESS_SKIP_UNIT=1)"
fi

if [[ "${MEV_STRESS_SKIP_E2E:-0}" != "1" ]]; then
  run_anvil_e2e
else
  echo "[SKIP] Anvil e2e (MEV_STRESS_SKIP_E2E=1)"
fi

echo ""
echo "[OK] MEV stress suite PASS (unit + e2e)"
