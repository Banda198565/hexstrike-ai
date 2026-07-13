#!/usr/bin/env bash
# security_gate.sh — mandatory pre-live ownership check (Mac operator only)
#
# Enforces:
#   1. HEXSTRIKE_HOST_ROLE=mac (not vps)
#   2. macOS (or FORCE_MAC_LIVE=1)
#   3. VAULT_PASSPHRASE + vault contains 'bot'
#   4. Derived signer address == KNOWN_BOT_ADDRESS (operator's own key)
#   5. Target in authorized_recipients
#   6. Nonce pending_gap == 0
#   7. No pending IR incidents flagged in artifacts/incidents/
#   8. HEXSTRIKE_TX_LIVE=1 present + CONFIRM=YES
#
# Usage:
#   bash scripts/security_gate.sh --target 0xPAYROLL
#   CONFIRM=YES HEXSTRIKE_TX_LIVE=1 bash scripts/security_gate.sh --target 0xPAYROLL --live
#
# Exit codes:
#   0 — READY
#   1 — HARD BLOCK (fail-closed)
#   2 — SOFT WARN (dry-run OK, live blocked)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET=""
MODE="check"
KNOWN_BOT="${KNOWN_BOT_ADDRESS:-${BOT_ADDRESS:-0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|--target=*) [[ "$1" == *=* ]] && TARGET="${1#*=}" || { TARGET="$2"; shift; }; shift ;;
    --live) MODE="live"; shift ;;
    --check) MODE="check"; shift ;;
    -h|--help)
      echo "Usage: security_gate.sh --target 0xADDR [--live|--check]"; exit 0 ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

pass=0; fail=0; warn=0
CHECKS=()
ok()   { CHECKS+=("✅ $*"); pass=$((pass+1)); }
bad()  { CHECKS+=("❌ $*"); fail=$((fail+1)); }
note() { CHECKS+=("⚠️  $*"); warn=$((warn+1)); }

# 1. Host role
HOST_ROLE="${HEXSTRIKE_HOST_ROLE:-}"
[[ -z "$HOST_ROLE" && "$(uname -s)" == "Darwin" ]] && HOST_ROLE=mac
[[ -z "$HOST_ROLE" && "$(uname -s)" == "Linux"  ]] && HOST_ROLE=vps

if [[ "$HOST_ROLE" == "mac" ]]; then
  ok "host_role=mac"
elif [[ "$HOST_ROLE" == "vps" ]]; then
  bad "host_role=vps — live broadcast forbidden"
else
  note "host_role unknown ($HOST_ROLE)"
fi

# 2. macOS (or force)
if [[ "$(uname -s)" == "Darwin" ]]; then
  ok "kernel=Darwin"
elif [[ "${FORCE_MAC_LIVE:-}" == "1" ]]; then
  note "FORCE_MAC_LIVE=1 (non-Darwin override)"
else
  [[ "$MODE" == "live" ]] && bad "not macOS — live requires Darwin or FORCE_MAC_LIVE=1" || note "not macOS (check mode)"
fi

# 3. Vault + bot key
if [[ -z "${VAULT_PASSPHRASE:-}" ]]; then
  bad "VAULT_PASSPHRASE unset"
else
  ok "VAULT_PASSPHRASE set"
  VAULT_JSON=$(./hexstrike vault list 2>&1 || echo '{}')
  if echo "$VAULT_JSON" | grep -q '"bot"'; then
    ok "vault contains 'bot'"
  else
    bad "vault missing 'bot' key"
  fi
fi

# 4. Signer ownership — derive address from vault key, compare to KNOWN_BOT
SIGNER_ADDR=""
if [[ -n "${VAULT_PASSPHRASE:-}" ]]; then
  SIGNER_ADDR=$(python3 - <<PY 2>/dev/null || true
import os, sys
sys.path.insert(0, "${ROOT}/src")
try:
    from hexstrike.mcp.fastmcp import VaultHandler
    from eth_account import Account
    key = VaultHandler().retrieve_key("bot")
    print(Account.from_key(key).address)
except Exception as exc:
    print(f"ERR:{exc}")
PY
)
fi

if [[ -z "$SIGNER_ADDR" || "$SIGNER_ADDR" == ERR:* ]]; then
  bad "cannot derive signer address (${SIGNER_ADDR:-empty})"
else
  SIGNER_LC=$(echo "$SIGNER_ADDR" | tr '[:upper:]' '[:lower:]')
  KNOWN_LC=$(echo "$KNOWN_BOT" | tr '[:upper:]' '[:lower:]')
  if [[ "$SIGNER_LC" == "$KNOWN_LC" ]]; then
    ok "signer matches KNOWN_BOT_ADDRESS ($SIGNER_ADDR)"
  else
    bad "signer ($SIGNER_ADDR) != KNOWN_BOT ($KNOWN_BOT) — refuse to sign for non-owner"
  fi
fi

# 5. Allowlist
if [[ -n "$TARGET" ]]; then
  ALLOW=$(python3 - <<PY 2>/dev/null || echo "false"
import json, sys
sys.path.insert(0, "${ROOT}/src")
from hexstrike.mcp.fastmcp import AllowlistManager
d = AllowlistManager().load()
recipients = {a.lower() for a in d.get("authorized_recipients", [])}
print("true" if "${TARGET}".lower() in recipients else "false")
PY
)
  if [[ "$ALLOW" == "true" ]]; then
    ok "target $TARGET in allowlist"
  else
    bad "target $TARGET NOT in authorized_recipients"
  fi
else
  note "no --target"
fi

# 6. Nonce
NONCE_JSON=$(./hexstrike tx nonce --address="$KNOWN_BOT" 2>/dev/null || echo '{}')
GAP=$(echo "$NONCE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('pending_gap',0))" 2>/dev/null || echo "0")
if [[ "${GAP:-0}" == "0" ]]; then
  ok "nonce pending_gap=0"
else
  bad "nonce pending_gap=$GAP — stuck tx must be resolved first"
fi

# 7. IR incidents
IR_DIR="${ROOT}/artifacts/incidents"
if [[ -d "$IR_DIR" ]]; then
  OPEN=$(find "$IR_DIR" -maxdepth 2 -name '*.open' 2>/dev/null | wc -l | tr -d ' ')
  if [[ "${OPEN:-0}" == "0" ]]; then
    ok "no open IR incidents"
  else
    bad "$OPEN open IR incident(s) in $IR_DIR — resolve before live"
  fi
else
  ok "no IR incidents directory (clean)"
fi

# 8. Live confirmation
if [[ "$MODE" == "live" ]]; then
  if [[ "${HEXSTRIKE_TX_LIVE:-}" != "1" ]]; then
    bad "HEXSTRIKE_TX_LIVE=1 required for live"
  else
    ok "HEXSTRIKE_TX_LIVE=1"
  fi
  if [[ "${CONFIRM:-}" != "YES" ]]; then
    bad "CONFIRM=YES required for live (typed confirmation)"
  else
    ok "CONFIRM=YES typed"
  fi
fi

# ── Report ──
echo "════════════════════════════════════════════════════════"
echo " Security gate — MODE=$MODE  HOST=$HOST_ROLE  TARGET=${TARGET:-none}"
echo "════════════════════════════════════════════════════════"
for c in "${CHECKS[@]}"; do echo "  $c"; done
echo ""
echo "  pass=$pass warn=$warn fail=$fail"

if [[ "$fail" -gt 0 ]]; then
  echo "RESULT: ❌ HARD BLOCK — do NOT proceed with live"
  exit 1
fi
if [[ "$MODE" == "live" ]]; then
  echo "RESULT: ✅ LIVE APPROVED — operator ownership verified"
  exit 0
fi
echo "RESULT: ✅ DRY-RUN OK — pass --live + CONFIRM=YES for broadcast"
exit 0
