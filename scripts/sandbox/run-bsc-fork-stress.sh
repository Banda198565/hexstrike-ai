#!/usr/bin/env bash
# run-bsc-fork-stress.sh — Variant D: BSC fork mempool + real pools + subset 08–11
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SANDBOX="$ROOT/scripts/sandbox"
RPC="http://127.0.0.1:${BSC_FORK_PORT:-8545}"
ART="$ROOT/artifacts/sandbox"
REPORT="$ART/mev-bsc-fork-stress-report.json"

wait_for_rpc() {
  local url="$1" tries="${2:-60}"
  for ((i = 1; i <= tries; i++)); do
    if curl -sf --max-time 5 "$url" \
      -X POST -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' | grep -q '"0x38"'; then
      return 0
    fi
    sleep 2
  done
  echo "[FAIL] BSC fork RPC not ready: $url"
  return 1
}

echo "=== VARIANT D: BSC fork setup ==="
chmod +x "$SANDBOX/setup-bsc-fork.sh" "$SANDBOX/stop-bsc-fork.sh"
bash "$SANDBOX/setup-bsc-fork.sh"
wait_for_rpc "$RPC"
bash "$SANDBOX/setup-anvil-env.sh" 2>/dev/null || true

export MEV_RPC_URL="$RPC"
export MEV_SANDBOX_ONLY=1
export MEV_ALLOWED_CHAINS="56"
export REDTEAM_CHAIN_ID="56"
export BSC_FORK_URL="${BSC_FORK_URL:-https://bsc-dataseed.binance.org}"

mkdir -p "$ART"
python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("artifacts/sandbox/redteam-report.json")
p.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "runs": []}, indent=2) + "\n")
PY

echo ""
echo "=== VARIANT D: seed pending Pancake swaps → mempool ==="
FORK_SEED_MEMPOOL=1 FORK_SEED_COUNT=3 python3 "$SANDBOX/mev/mempool_scanner.py"

echo ""
echo "=== VARIANT D: mempool scan (read-only) ==="
python3 "$SANDBOX/mev/mempool_scanner.py"

echo ""
echo "=== VARIANT D: fork offensive (real WBNB/USDT reserves + mempool PnL) ==="
FORK_SCAN_MEMPOOL=1 FORK_FLUSH_MEMPOOL=1 python3 "$SANDBOX/mev/fork_offensive.py"

echo ""
echo "=== VARIANT D: assert mempool + fork sim ==="
python3 "$SANDBOX/mev/fork_e2e_assert.py" --mode mempool --report "$REPORT"
python3 "$SANDBOX/mev/fork_e2e_assert.py" --mode fork --report "$REPORT"

echo ""
echo "=== VARIANT D: mock engines on BSC fork (JIT + backrun deploy path) ==="
JIT_FORCE_DEMO=1 python3 "$SANDBOX/mev/jit_engine.py" || true
python3 "$SANDBOX/mev/backrun_engine.py" || true
python3 "$SANDBOX/mev/fork_e2e_assert.py" --mode mock --report "$REPORT"

echo ""
echo "=== VARIANT D: redteam 09–11 on BSC fork (08 = fork_offensive real pools) ==="
bash "$SANDBOX/redteam/09-mev-frontrun-gas-race.sh"
bash "$SANDBOX/redteam/10-mev-jit-liquidity.sh"
bash "$SANDBOX/redteam/11-mev-backrun-arb.sh"
python3 "$SANDBOX/mev/fork_e2e_assert.py" --mode redteam --report "$REPORT"

echo ""
echo "=== VARIANT D: unified fork stress report ==="
python3 "$SANDBOX/mev/fork_e2e_assert.py" --mode all --report "$REPORT"
echo "[OK] report → $REPORT"
echo "[OK] Variant D BSC fork stress PASS"
