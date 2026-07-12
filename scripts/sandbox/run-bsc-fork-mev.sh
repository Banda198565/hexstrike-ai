#!/usr/bin/env bash
# run-bsc-fork-mev.sh — BSC fork offensive sim (no mainnet tx submit)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANDBOX="$ROOT/scripts/sandbox"

chmod +x "$SANDBOX/setup-bsc-fork.sh"
"$SANDBOX/setup-bsc-fork.sh"

export MEV_RPC_URL="http://127.0.0.1:${BSC_FORK_PORT:-8545}"
export MEV_SANDBOX_ONLY=1
export MEV_ALLOWED_CHAINS="56"

python3 "$SANDBOX/mev/fork_offensive.py"
