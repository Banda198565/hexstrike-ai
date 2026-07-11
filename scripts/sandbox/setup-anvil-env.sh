#!/usr/bin/env bash
# setup-anvil-env.sh — create gitignored anvil.env with Foundry public test keys
set -euo pipefail

SANDBOX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SANDBOX/anvil.env"
EXAMPLE="$SANDBOX/anvil.env.example"

if [[ -f "$OUT" ]]; then
  echo "[OK]   $OUT already exists (not overwritten)"
  exit 0
fi

# Anvil default mnemonic — account #1 (public, local-only)
cat >"$OUT" <<'ENV'
# LOCAL SANDBOX ONLY — Anvil public test keys. Never use in production.
RPC_URL=http://127.0.0.1:8545
UPSTREAM_RPC=http://127.0.0.1:8545
PROXY_PORT=8546
CHAIN_ID=31337

BOT_ADDRESS=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
BOT_PRIVATE_KEY=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b774b828
FUNDER_ADDRESS=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266

THRESHOLD_WEI=500000000000000000
MIN_GAS_WEI=10000000000000000
RESCUE_VALUE_WEI=1000000000000000
POLL_INTERVAL_SEC=10

HARDENING_ENABLED=false
DIRECT_RPC_URL=http://127.0.0.1:8545
MAX_BALANCE_DELTA_WEI=0
ANOMALY_STALE_TIMEOUT_SEC=120
GUARD_RPC_TIMEOUT_SEC=10
ENV

echo "[OK]   Created $OUT (gitignored)"
echo "       Template reference: $EXAMPLE"
