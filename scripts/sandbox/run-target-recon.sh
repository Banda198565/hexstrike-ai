#!/usr/bin/env bash
# run-target-recon.sh — read-only validation of real target from artifacts (BSC public RPC + optional fork)
set -euo pipefail

SANDBOX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SANDBOX/../.." && pwd)"
PROFILE="$ROOT/artifacts/sandbox/target-profile.json"
REPORT="$ROOT/artifacts/sandbox/target-recon-report.json"

python3 "$SANDBOX/generate-target-profile.py" >/dev/null

# shellcheck source=/dev/null
source "$SANDBOX/resolve-anvil-env.sh" >/dev/null 2>&1 || true
ENV_FILE="${SANDBOX_ENV:-$("$SANDBOX/resolve-anvil-env.sh")}"
# shellcheck disable=SC1090
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

HOT="$(python3 -c "import json; print(json.load(open('$PROFILE'))['primary_target']['address'])")"
BSC_RPC="$(python3 -c "import json; print(json.load(open('$PROFILE'))['rpc_endpoints']['bsc_public'])")"
LOCAL_RPC="${RPC_URL:-http://127.0.0.1:8545}"

echo "=== REAL TARGET RECON (read-only) ==="
echo "Target: $HOT"
echo "BSC RPC: $BSC_RPC"

command -v cast >/dev/null || { echo "[FAIL] cast required"; exit 1; }

read_chain() {
  local rpc="$1" label="$2"
  local bal nonce code chain
  bal="$(cast balance "$HOT" --rpc-url "$rpc" 2>/dev/null || echo ERROR)"
  nonce="$(cast nonce "$HOT" --rpc-url "$rpc" 2>/dev/null || echo ERROR)"
  code="$(cast code "$HOT" --rpc-url "$rpc" 2>/dev/null || echo ERROR)"
  chain="$(cast chain-id --rpc-url "$rpc" 2>/dev/null || echo ERROR)"
  echo "[$label] chain=$chain balance_wei=$bal nonce=$nonce is_contract=$([ "$code" != "0x" ] && echo yes || echo no)"
  python3 - "$REPORT" "$label" "$rpc" "$bal" "$nonce" "$code" "$chain" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
report_path = Path(sys.argv[1])
label, rpc, bal, nonce, code, chain = sys.argv[2:8]
data = {"generated_at": datetime.now(timezone.utc).isoformat(), "target": None, "checks": []}
if report_path.is_file():
    data = json.loads(report_path.read_text())
data["target"] = data.get("target") or __import__("json").load(open("artifacts/sandbox/target-profile.json"))["primary_target"]["address"]
data["checks"].append({
    "source": label,
    "rpc": rpc,
    "balance_wei": bal,
    "nonce": nonce,
    "has_code": code not in ("0x", "ERROR"),
    "chain_id": chain,
})
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(data, indent=2) + "\n")
PY
}

read_chain "$BSC_RPC" "bsc_live"

if curl -sf --max-time 3 "$LOCAL_RPC" -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' >/dev/null 2>&1; then
  read_chain "$LOCAL_RPC" "local_fork"
  echo ""
  echo "[fork] Simulating low-balance trigger (anvil_setBalance — fork only)..."
  LOW=300000000000000000
  cast rpc anvil_setBalance "$HOT" "$(printf '0x%x' "$LOW")" --rpc-url "$LOCAL_RPC" >/dev/null 2>&1 || true
  python3 "$SANDBOX/dummy_bot.py" --once --dry-run 2>/dev/null || echo "[warn] dummy_bot --once skipped (set BOT_PRIVATE_KEY for signing tests)"
  cast rpc anvil_setBalance "$HOT" "0x56BC75E2D63100000" --rpc-url "$LOCAL_RPC" >/dev/null 2>&1 || true
else
  echo "[skip] No local Anvil fork on $LOCAL_RPC — run setup-real-target-fork.sh first"
fi

echo ""
echo "[OK] Report: $REPORT"
python3 -m json.tool "$REPORT" 2>/dev/null | head -40
