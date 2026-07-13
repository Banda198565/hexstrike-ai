#!/usr/bin/env bash
# Pipeline: Transaction + Discovery (parallel) + Rescue check
#   bash scripts/pipeline_transaction_discovery.sh
#   bash scripts/pipeline_transaction_discovery.sh --live   # Mac with keys only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

echo "=== Pipeline: transaction + discovery ==="
if [[ "$LIVE" -eq 1 ]]; then
  export HEXSTRIKE_TX_LIVE=1
  export TARGET_ADDRESS="${TARGET_ADDRESS:-${TARGET_WALLET:-0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA}}"
fi

./hexstrike sync --mcp
./hexstrike agent run pipeline --pipeline transaction-discovery
./hexstrike orchestrator reload
echo "=== DONE — artifacts/agents/*_result.json  tx_logs/ ==="
