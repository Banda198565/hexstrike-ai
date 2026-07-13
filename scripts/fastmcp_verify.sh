#!/usr/bin/env bash
# fastmcp_verify.sh — Mac operator readiness check for FastMCP live mode
#
# Checks: env exports, vault unlock, allowlist, dry-run artifact (or runs one),
#         signer address vs BOT_ADDRESS, nonce gap, live broadcast artifact.
#
# Usage:
#   export VAULT_PASSPHRASE='...'
#   export BOT_PRIVATE_KEY='0x...'
#   bash scripts/fastmcp_verify.sh --target 0xPAYROLL
#
#   # Run dry-run inline if no tx_logs/latest artifact:
#   bash scripts/fastmcp_verify.sh --target 0xPAYROLL --run-dry-run
#
#   # After live broadcast:
#   export HEXSTRIKE_TX_LIVE=1
#   bash scripts/fastmcp_verify.sh --target 0xPAYROLL
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

TARGET="${TARGET_ADDRESS:-${TARGET_WALLET:-}}"
RUN_DRY=0
ADD_RECIPIENT=""

usage() {
  cat <<'EOF'
Usage: bash scripts/fastmcp_verify.sh [options]

Options:
  --target 0xADDR       Payroll/recipient to verify against allowlist
  --add-recipient 0xADDR Add to allowlist before dry-run (with --run-dry-run)
  --run-dry-run          Execute dry-run cycle if no latest artifact exists
  -h, --help             Show this help

Reads:  tx_logs/latest/fastmcp_cycle.json, tx_logs/latest_dry_run.json
Writes: tx_logs/latest_dry_run.json (when --run-dry-run)
        tx_logs/latest_live.json (copy when LIVE=1 and broadcast present)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|--target=*)
      [[ "$1" == *=* ]] && TARGET="${1#*=}" || { TARGET="$2"; shift; }
      shift
      ;;
    --add-recipient|--add-recipient=*)
      [[ "$1" == *=* ]] && ADD_RECIPIENT="${1#*=}" || { ADD_RECIPIENT="$2"; shift; }
      shift
      ;;
    --run-dry-run) RUN_DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

BOT_ADDR="${BOT_ADDRESS:-${PUBLIC_ADDRESS:-${FUNDER_ADDRESS:-}}}"
LIVE_FLAG="${HEXSTRIKE_TX_LIVE:-unset}"

VERDICTS=()
pass() { VERDICTS+=("✅ $*"); echo "  ✅ $*"; }
warn() { VERDICTS+=("⚠️  $*"); echo "  ⚠️  $*"; }
fail() { VERDICTS+=("❌ $*"); echo "  ❌ $*"; }
block() { VERDICTS+=("🔒 $*"); echo "  🔒 $*"; }

jq_or_python() {
  local expr="$1"
  local file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r "$expr" "$file" 2>/dev/null || echo ""
  else
    python3 - "$expr" "$file" <<'PY'
import json, sys
expr, path = sys.argv[1], sys.argv[2]
with open(path) as f:
    d = json.load(f)
# Simple jq-like paths: .a.b.c or multiple comma-separated
for part in expr.replace("'", "").split(","):
    part = part.strip()
    if not part.startswith("."):
        continue
    keys = part.lstrip(".").split(".")
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = None
            break
    print("" if cur is None else cur)
PY
  fi
}

echo "════════════════════════════════════════════════════════"
echo " FastMCP verify — LIVE_MODE_VERIFICATION"
echo " ROOT: $ROOT"
echo "════════════════════════════════════════════════════════"

# ── 1. Env exports ──
echo ""
echo "[CHECK] Vault / Key / Live status:"
echo "  VAULT: $( [[ -n "${VAULT_PASSPHRASE:-}" ]] && echo SET || echo unset )"
echo "  KEY:   $( [[ -n "${BOT_PRIVATE_KEY:-}" ]] && echo SET || echo unset )"
echo "  LIVE:  $LIVE_FLAG"
echo "  BOT:   ${BOT_ADDR:-unset}"
echo "  TARGET:${TARGET:-unset}"

ENV_OK=1
[[ -n "${VAULT_PASSPHRASE:-}" ]] || { fail "VAULT_PASSPHRASE not set"; ENV_OK=0; }
if [[ -z "${BOT_PRIVATE_KEY:-}" ]]; then
  warn "BOT_PRIVATE_KEY unset — OK only if bot key already in vault"
else
  pass "BOT_PRIVATE_KEY exported"
fi
[[ "$ENV_OK" -eq 1 ]] && pass "VAULT_PASSPHRASE exported"

if [[ "$LIVE_FLAG" == "1" ]]; then
  pass "HEXSTRIKE_TX_LIVE=1 — broadcast enabled"
else
  warn "LIVE: unset — dry-run only (expected before live)"
fi

# ── 2. Vault list ──
echo ""
echo "[CHECK] Vault list:"
VAULT_JSON=""
if VAULT_JSON=$("$HEXSTRIKE" vault list 2>&1); then
  echo "$VAULT_JSON"
  if echo "$VAULT_JSON" | grep -q '"bot"'; then
    pass "vault contains key 'bot'"
  else
    fail "vault unlocked but 'bot' key missing — run: hexstrike vault store-key bot"
  fi
else
  echo "$VAULT_JSON"
  if echo "$VAULT_JSON" | grep -qi "invalid passphrase"; then
    fail "PASSPHRASE MISMATCH — wrong VAULT_PASSPHRASE for existing keystore"
  else
    fail "vault list failed — run: hexstrike vault init && hexstrike vault store-key bot"
  fi
fi

# ── 3. Allowlist ──
echo ""
echo "[CHECK] Allowlist:"
ALLOW_JSON=$(python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "${ROOT}/src")
from hexstrike.mcp.fastmcp import AllowlistManager
print(json.dumps(AllowlistManager().load(), indent=2))
PY
)
echo "$ALLOW_JSON"

TARGET_LC="$(python3 -c "print('${TARGET:-}'.lower())" 2>/dev/null || echo "")"
if [[ -z "$TARGET" ]]; then
  warn "No --target / TARGET_ADDRESS — skip payroll allowlist match"
elif echo "$ALLOW_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
target = '${TARGET_LC}'.lower()
recipients = {a.lower() for a in data.get('authorized_recipients', [])}
sys.exit(0 if target in recipients else 1)
" 2>/dev/null; then
  pass "target $TARGET in authorized_recipients"
else
  block "BLOCKED (gate) — $TARGET not in authorized_recipients"
  echo "  hint: python3 scripts/run_fastmcp_combat_live.py --target $TARGET --add-recipient $TARGET --dry-run"
fi

# ── 4. Nonce gap ──
echo ""
echo "[CHECK] Nonce:"
if [[ -n "$BOT_ADDR" ]]; then
  NONCE_JSON=$("$HEXSTRIKE" tx nonce --address="$BOT_ADDR" 2>/dev/null || echo '{}')
  echo "$NONCE_JSON" | head -12
  GAP=$(echo "$NONCE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('pending_gap',0))" 2>/dev/null || echo "0")
  if [[ "${GAP:-0}" == "0" ]]; then
    pass "nonce pending_gap=0"
  else
    warn "nonce pending_gap=$GAP — review before live"
  fi
else
  warn "BOT_ADDRESS unset — skip nonce check"
fi

# ── 5. Dry-run artifact ──
echo ""
echo "[CHECK] Dry-run JSON:"
LATEST_DIR="${ROOT}/tx_logs/latest"
DRY_FILE="${ROOT}/tx_logs/latest_dry_run.json"
CYCLE_FILE="${LATEST_DIR}/fastmcp_cycle.json"

if [[ "$RUN_DRY" -eq 1 && -n "$TARGET" ]]; then
  echo "  Running inline dry-run..."
  DRY_ARGS=(--target "$TARGET" --dry-run)
  [[ -n "$ADD_RECIPIENT" ]] && DRY_ARGS+=(--add-recipient "$ADD_RECIPIENT")
  python3 "$ROOT/scripts/run_fastmcp_combat_live.py" "${DRY_ARGS[@]}" > "$DRY_FILE"
  mkdir -p "$LATEST_DIR"
  cp -a "$DRY_FILE" "$CYCLE_FILE" 2>/dev/null || cp -a "$DRY_FILE" "$CYCLE_FILE"
elif [[ -f "$DRY_FILE" ]]; then
  echo "  source: $DRY_FILE"
elif [[ -f "$CYCLE_FILE" ]]; then
  echo "  source: $CYCLE_FILE"
  DRY_FILE="$CYCLE_FILE"
else
  warn "No dry-run artifact — run with --run-dry-run or:"
  echo "  python3 scripts/run_fastmcp_combat_live.py --target 0xPAYROLL --add-recipient 0xPAYROLL --dry-run > tx_logs/latest_dry_run.json"
  DRY_FILE=""
fi

if [[ -n "$DRY_FILE" && -f "$DRY_FILE" ]]; then
  echo "  fields: success | gate.allowed | sign.from | sign.hash | dry_run"
  python3 - <<PY
import json
from pathlib import Path
d = json.loads(Path("${DRY_FILE}").read_text())
print(f"  success:      {d.get('success')}")
print(f"  gate.allowed: {d.get('gate', {}).get('allowed')}")
print(f"  sign.from:    {d.get('sign', {}).get('from', 'MISSING')}")
print(f"  sign.hash:    {d.get('sign', {}).get('hash', 'MISSING')}")
print(f"  dry_run:      {d.get('dry_run')}")
PY

  SUCCESS=$(jq_or_python ".success" "$DRY_FILE" | head -1)
  GATE=$(jq_or_python ".gate.allowed" "$DRY_FILE" | head -1)
  SIGN_HASH=$(jq_or_python ".sign.hash" "$DRY_FILE" | head -1)
  SIGN_FROM=$(jq_or_python ".sign.from" "$DRY_FILE" | head -1)

  [[ "$SUCCESS" == "True" || "$SUCCESS" == "true" ]] && pass "dry-run success=true" || fail "dry-run success=false"
  [[ "$GATE" == "True" || "$GATE" == "true" ]] && pass "gate.allowed=true" || block "BLOCKED (gate) — dry-run gate failed"

  if [[ -z "$SIGN_HASH" || "$SIGN_HASH" == "null" || "$SIGN_HASH" == "MISSING" ]]; then
    fail "WRONG KEY — sign.hash missing"
  else
    pass "sign.hash present"
  fi

  if [[ -n "$BOT_ADDR" && -n "$SIGN_FROM" && "$SIGN_FROM" != "null" ]]; then
    MATCH=$(python3 -c "print(1 if '${SIGN_FROM}'.lower()=='${BOT_ADDR}'.lower() else 0)" 2>/dev/null || echo "0")
    if [[ "$MATCH" == "1" ]]; then
      pass "sign.from matches BOT_ADDRESS"
    elif [[ -n "${BOT_PRIVATE_KEY:-}" ]]; then
      fail "WRONG KEY — sign.from ($SIGN_FROM) != BOT_ADDRESS ($BOT_ADDR)"
    else
      warn "sign.from ($SIGN_FROM) != BOT_ADDRESS ($BOT_ADDR) — vault may hold lab/wrong key"
    fi
  fi
fi

# ── 6. Live broadcast (optional) ──
echo ""
echo "[CHECK] Live broadcast:"
LIVE_FILE="${ROOT}/tx_logs/latest_live.json"
if [[ "$LIVE_FLAG" == "1" ]]; then
  if [[ -f "$CYCLE_FILE" ]]; then
    cp -a "$CYCLE_FILE" "$LIVE_FILE" 2>/dev/null || true
  fi
  SRC="${LIVE_FILE}"
  [[ -f "$SRC" ]] || SRC="$CYCLE_FILE"
  if [[ -f "$SRC" ]]; then
    BC_HASH=$(jq_or_python ".broadcast.hash" "$SRC" | head -1)
    WATCH=$(jq_or_python ".watch.status" "$SRC" | head -1)
    echo "  broadcast.hash: ${BC_HASH:-unset}"
    echo "  watch.status:   ${WATCH:-unset}"
    if [[ -n "$BC_HASH" && "$BC_HASH" != "null" ]]; then
      pass "broadcast hash recorded: $BC_HASH"
    else
      warn "no broadcast.hash yet — live cycle may not have completed"
    fi
  else
    warn "no live artifact at tx_logs/latest_live.json"
  fi
else
  echo "  LIVE unset — skipping broadcast check (dry-run only)"
fi

# ── Final verdict ──
echo ""
echo "════════════════════════════════════════════════════════"
echo " VERDICT"
echo "════════════════════════════════════════════════════════"

HAS_BLOCK=0
HAS_FAIL=0
for v in "${VERDICTS[@]}"; do
  echo "  $v"
  [[ "$v" == 🔒* ]] && HAS_BLOCK=1
  [[ "$v" == ❌* ]] && HAS_FAIL=1
done

echo ""
if [[ "$HAS_FAIL" -eq 1 ]]; then
  echo "RESULT: ❌ NOT READY — fix failures above"
  exit 1
elif [[ "$HAS_BLOCK" -eq 1 ]]; then
  echo "RESULT: 🔒 BLOCKED (gate) — add recipient to allowlist"
  exit 2
elif [[ "$LIVE_FLAG" == "1" ]]; then
  echo "RESULT: ✅ LIVE MODE ACTIVE — verify broadcast.hash on BscScan"
  exit 0
else
  echo "RESULT: ✅ READY FOR LIVE — export HEXSTRIKE_TX_LIVE=1 when operator confirms"
  exit 0
fi
