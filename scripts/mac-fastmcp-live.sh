#!/usr/bin/env bash
# mac-fastmcp-live.sh — Mac operator companion for FastMCP live broadcast
#
# Usage (Mac only):
#   export VAULT_PASSPHRASE='...'
#   export BOT_PRIVATE_KEY='0x...'
#   bash scripts/mac-fastmcp-live.sh --target 0xPAYROLL --dry-run
#   bash scripts/mac-fastmcp-live.sh --target 0xPAYROLL --live   # requires typed CONFIRM
#
# Refuses to run when HEXSTRIKE_HOST_ROLE=vps or when /opt/hexstrike-ai is CWD
# unless FORCE_MAC_LIVE=1 (emergency override — not recommended).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET="${TARGET_ADDRESS:-}"
VALUE="${TX_VALUE:-0.001bnb}"
ADD_RECIPIENT=""
MODE="dry-run"
FORCE="${FORCE_MAC_LIVE:-0}"

usage() {
  cat <<'EOF'
Usage: bash scripts/mac-fastmcp-live.sh --target 0xPAYROLL [--dry-run|--live]

Options:
  --target 0xADDR          Payroll recipient (required)
  --add-recipient 0xADDR   Allowlist before cycle (defaults to --target)
  --value 0.001bnb         Native transfer value
  --dry-run                Verify + dry-run only (default)
  --live                   Broadcast (requires CONFIRM=YES and HEXSTRIKE_TX_LIVE=1)
  -h, --help
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
    --value|--value=*)
      [[ "$1" == *=* ]] && VALUE="${1#*=}" || { VALUE="$2"; shift; }
      shift
      ;;
    --dry-run) MODE="dry-run"; shift ;;
    --live) MODE="live"; shift ;;
    -h|--help) usage; exit 0 ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[mac-live] $*"; }
die() { echo "[mac-live] FAIL: $*" >&2; exit 1; }

[[ -n "$TARGET" ]] || die "--target required"
ADD_RECIPIENT="${ADD_RECIPIENT:-$TARGET}"

# Host role guard
if [[ "${HEXSTRIKE_HOST_ROLE:-}" == "vps" && "$FORCE" != "1" ]]; then
  die "HEXSTRIKE_HOST_ROLE=vps — use Mac for live. Set FORCE_MAC_LIVE=1 only in emergency."
fi
if [[ "$ROOT" == "/opt/hexstrike-ai" && "$FORCE" != "1" ]]; then
  die "CWD is /opt/hexstrike-ai (VPS path) — live belongs on Mac checkout"
fi
if [[ "$(uname -s)" != "Darwin" && "$FORCE" != "1" && "$MODE" == "live" ]]; then
  die "Live mode requires macOS (or FORCE_MAC_LIVE=1). Current: $(uname -s)"
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

[[ -n "${VAULT_PASSPHRASE:-}" ]] || die "VAULT_PASSPHRASE required"
BOT_ADDR="${BOT_ADDRESS:-${PUBLIC_ADDRESS:-0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846}}"

log "MODE=$MODE TARGET=$TARGET BOT=$BOT_ADDR"

# 1. Vault
./hexstrike vault init || true
if [[ -n "${BOT_PRIVATE_KEY:-}" ]]; then
  ./hexstrike vault store-key bot || true
fi
./hexstrike vault list

# 2. Verify readiness
log "fastmcp_verify --run-dry-run"
bash scripts/fastmcp_verify.sh --target "$TARGET" --add-recipient "$ADD_RECIPIENT" --run-dry-run

# 3. Dry-run or live
if [[ "$MODE" == "dry-run" ]]; then
  log "Dry-run cycle only — broadcast blocked"
  bash scripts/fastmcp_live_cycle.sh \
    --target "$TARGET" \
    --add-recipient "$ADD_RECIPIENT" \
    --value "$VALUE" \
    --skip-verify
  log "DONE dry-run — review tx_logs/latest/ then re-run with --live"
  exit 0
fi

# Live path
[[ -n "${BOT_PRIVATE_KEY:-}" || -n "${VAULT_PASSPHRASE:-}" ]] || \
  die "live needs BOT_PRIVATE_KEY or vault with bot key"

if [[ "${CONFIRM:-}" != "YES" ]]; then
  die "Refusing live without CONFIRM=YES (typed confirmation). Example:
  CONFIRM=YES HEXSTRIKE_TX_LIVE=1 bash scripts/mac-fastmcp-live.sh --target $TARGET --live"
fi

# Mandatory pre-live security gate — operator ownership check
export HEXSTRIKE_TX_LIVE=1
log "Pre-live security gate..."
if ! bash scripts/security_gate.sh --target "$TARGET" --live; then
  die "security_gate.sh refused live broadcast — see verdict above"
fi
log "LIVE broadcast starting..."
bash scripts/fastmcp_live_cycle.sh \
  --target "$TARGET" \
  --add-recipient "$ADD_RECIPIENT" \
  --value "$VALUE" \
  --live \
  --skip-verify

log "Post-live verify"
bash scripts/fastmcp_verify.sh --target "$TARGET" || true
log "DONE — check tx_logs/latest/fastmcp_live_summary.json and BscScan"
