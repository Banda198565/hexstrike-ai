#!/usr/bin/env bash
# run-field-targets-recon.sh — P1 full field recon (all report wallets + infra)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export WALLETS_FILE="${WALLETS_FILE:-$ROOT/scripts/sandbox/field-targets-full.json}"
export BSC_HTTP_URL="${BSC_HTTP_URL:-https://bsc-dataseed.binance.org}"

echo "=== Field recon (read-only) ==="
echo "WALLETS_FILE=$WALLETS_FILE"
python3 "$ROOT/scripts/sandbox/field_targets_recon.py"
echo "=== MCP smoke (evm + explorer) ==="
bash "$ROOT/scripts/mcp-smoke-test.sh"
echo "[OK] field-recon complete → artifacts/sandbox/field-recon-bundle.json"
