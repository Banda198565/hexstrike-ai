#!/bin/bash
# E: Local crypto key-surface audit (run on Mac)
set -euo pipefail
ROOT="${CRYPTO_HOME:-$HOME}"
REPORT="${1:-${OUTPUT:-/tmp/crypto-audit-$(date +%Y%m%d-%H%M%S).txt}}"

{
  echo "=== CRYPTO KEY SURFACE AUDIT ==="
  date
  echo "User: $(whoami)"
  echo

  echo "--- Key files ---"
  for f in "$HOME/proof-key.txt" "$HOME/.ethereum/keystore"/* "$HOME/.config/solana/id.json"; do
    [[ -e "$f" || -L "$f" ]] && ls -la "$f" 2>/dev/null
  done
  echo

  echo "--- Symlinks to Eva ---"
  ls -la "$HOME/proof-key.txt" "$HOME/Desktop/redteam" "$HOME/.cursor/skills/geth-wallet-hunt" 2>/dev/null || true
  echo

  echo "--- Grep PRIVATE_KEY in home (paths only) ---"
  grep -RIl --exclude-dir={node_modules,.git,Library,Cache,cache} \
    -E 'PRIVATE_KEY|proof-key|mnemonic|seed phrase' "$HOME" 2>/dev/null | head -30 || true
  echo

  echo "--- Cursor MCP config (no secrets dump) ---"
  [[ -f "$HOME/.cursor/mcp.json" ]] && jq 'walk(if type=="object" and has("env") then .env="[REDACTED]" else . end)' "$HOME/.cursor/mcp.json" 2>/dev/null || echo "no mcp.json"
  echo

  echo "--- npm/pip crypto deps (top) ---"
  pip list 2>/dev/null | grep -iE 'web3|eth|solana|injective|wallet' || true
  echo

  echo "--- Recommendations ---"
  echo "1. proof-key.txt: chmod 600, only on Eva, not in Cursor workspace"
  echo "2. No signing tools in MCP"
  echo "3. Audit: pip/npm outdated + pip-audit / npm audit"
} | tee "$REPORT"

echo "Saved: $REPORT"
