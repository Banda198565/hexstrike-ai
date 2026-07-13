#!/usr/bin/env bash
# vps-almalinux-fastmcp-bootstrap.sh — AlmaLinux/RHEL VPS FastMCP dry-run contour
#
# Run ON VPS (AlmaLinux 8/9 or RHEL-compatible) as root or with sudo:
#   cd /opt/hexstrike-ai && bash scripts/vps-almalinux-fastmcp-bootstrap.sh
#
# What it does:
#   dnf packages → venv → vault lab init → sync → verify → dry-run cycle
#
# What it REFUSES:
#   HEXSTRIKE_TX_LIVE=1 / real operator BOT_PRIVATE_KEY live broadcast
#   Live broadcast belongs on Mac only.
#
# Env overrides:
#   HEXSTRIKE_DIR=/opt/hexstrike-ai
#   TARGET_ADDRESS=0x...
#   VAULT_PASSPHRASE=...          # lab passphrase for VPS vault
#   BOT_PRIVATE_KEY=0x...         # LAB key only (optional; generated if missing)
#   SKIP_DNF=1 SKIP_VENV=1 SKIP_VERIFY=1
set -euo pipefail

INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
# Prefer repo root when script lives inside a checkout
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$SCRIPT_ROOT/hexstrike" ]]; then
  INSTALL_DIR="$SCRIPT_ROOT"
fi

TARGET="${TARGET_ADDRESS:-${TARGET_WALLET:-0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA}}"
SKIP_DNF="${SKIP_DNF:-0}"
SKIP_VENV="${SKIP_VENV:-0}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"

log() { echo "[alma-fastmcp] $*"; }
die() { echo "[alma-fastmcp] FAIL: $*" >&2; exit 1; }
warn() { echo "[alma-fastmcp] WARN: $*"; }

echo "════════════════════════════════════════════════════════"
echo " AlmaLinux / RHEL — FastMCP VPS bootstrap (DRY-RUN ONLY)"
echo " INSTALL: $INSTALL_DIR"
echo " TARGET:  $TARGET"
echo "════════════════════════════════════════════════════════"

# ── Safety: refuse live mode on VPS ──
if [[ "${HEXSTRIKE_TX_LIVE:-}" == "1" ]]; then
  die "HEXSTRIKE_TX_LIVE=1 is forbidden on VPS. Unset it and run live only on Mac."
fi
unset HEXSTRIKE_TX_LIVE || true
export DRY_RUN=true

# ── OS detect ──
if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  log "OS: ${PRETTY_NAME:-unknown}"
fi

PKG=""
if command -v dnf >/dev/null 2>&1; then
  PKG=dnf
elif command -v yum >/dev/null 2>&1; then
  PKG=yum
else
  warn "No dnf/yum — skip package install (Debian/cloud agent? set SKIP_DNF=1)"
  SKIP_DNF=1
fi

# ── Packages ──
if [[ "$SKIP_DNF" -eq 0 ]]; then
  log "Installing packages via $PKG..."
  $PKG install -y git python3 python3-pip python3-devel gcc openssl-devel jq curl \
    || die "package install failed"
else
  log "SKIP_DNF=1 — package install skipped"
fi

command -v python3 >/dev/null || die "python3 required"
command -v git >/dev/null || die "git required"

# ── Repo ──
if [[ ! -d "$INSTALL_DIR" ]]; then
  die "Missing $INSTALL_DIR — clone first:
  sudo mkdir -p /opt && sudo git clone https://github.com/Banda198565/hexstrike-ai.git /opt/hexstrike-ai"
fi
cd "$INSTALL_DIR"
[[ -x ./hexstrike ]] || chmod +x ./hexstrike 2>/dev/null || true

# ── Venv ──
VENV="${INSTALL_DIR}/hexstrike_env"
if [[ "$SKIP_VENV" -eq 0 ]]; then
  if [[ ! -d "$VENV" ]]; then
    log "Create venv → $VENV"
    python3 -m venv "$VENV"
  fi
  # shellcheck source=/dev/null
  source "$VENV/bin/activate"
  log "pip install requirements + vault deps..."
  pip install -q -U pip
  pip install -q -r requirements.txt
  pip install -q eth-account cryptography
else
  if [[ -d "$VENV" ]]; then
    # shellcheck source=/dev/null
    source "$VENV/bin/activate"
  fi
  log "SKIP_VENV=1"
fi

# ── .env minimal ──
if [[ ! -f .env ]]; then
  log "Create minimal .env (no operator secrets)"
  cat >.env <<ENV
CHAIN_ID=56
RPC_URL=${RPC_URL:-https://bsc-dataseed.binance.org}
TARGET_WALLET=${TARGET}
BOT_ADDRESS=${BOT_ADDRESS:-0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846}
DRY_RUN=true
HEXSTRIKE_TX_LIVE=
ENV
  chmod 600 .env
fi

set -a
# shellcheck source=/dev/null
source .env
set +a

export RPC_URL="${RPC_URL:-https://bsc-dataseed.binance.org}"
export CHAIN_ID="${CHAIN_ID:-56}"
export TARGET_ADDRESS="$TARGET"

# Lab vault passphrase (never print)
if [[ -z "${VAULT_PASSPHRASE:-}" ]]; then
  export VAULT_PASSPHRASE="vps-lab-$(hostname -s 2>/dev/null || echo host)-$(date +%Y%m)"
  warn "VAULT_PASSPHRASE was empty — generated lab passphrase for this session (not persisted to disk as plaintext)"
fi

# Lab key only — never require operator key on VPS
if [[ -z "${BOT_PRIVATE_KEY:-}" ]]; then
  export BOT_PRIVATE_KEY="0x$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  warn "BOT_PRIVATE_KEY unset — generated LAB key for vault dry-run (not operator key)"
fi

log "Env: VAULT=$( [[ -n "${VAULT_PASSPHRASE:-}" ]] && echo SET || echo unset ) KEY=SET LIVE=unset"

# ── Vault lab ──
log "Vault init + store-key bot (lab)..."
./hexstrike vault init || die "vault init failed"
./hexstrike vault store-key bot || die "vault store-key failed"
./hexstrike vault list

# ── Sync ──
log "MCP sync..."
./hexstrike sync --mcp || warn "sync had warnings"

# ── Combat verify ──
if [[ "$SKIP_VERIFY" -eq 0 ]]; then
  log "Combat integration verify..."
  bash scripts/verify-combat-integration.sh "$INSTALL_DIR" || warn "combat verify had failures"
else
  log "SKIP_VERIFY=1"
fi

# ── FastMCP verify + dry-run ──
log "FastMCP verify --run-dry-run..."
if [[ -x scripts/fastmcp_verify.sh ]]; then
  bash scripts/fastmcp_verify.sh --target "$TARGET" --run-dry-run \
    || warn "fastmcp_verify exited non-zero (check allowlist / vault)"
else
  die "scripts/fastmcp_verify.sh missing — pull latest branch"
fi

# ── Nonce (read-only) ──
log "Nonce probe..."
./hexstrike tx nonce || warn "nonce probe failed"

# ── Pipeline dry-run ──
if [[ -x scripts/pipeline_transaction_discovery.sh ]]; then
  log "Pipeline transaction-discovery (dry)..."
  bash scripts/pipeline_transaction_discovery.sh || warn "pipeline warnings"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo " AlmaLinux FastMCP VPS — DONE (DRY-RUN)"
echo "════════════════════════════════════════════════════════"
echo " Artifacts: $INSTALL_DIR/tx_logs/latest/"
echo " Next on VPS:"
echo "   bash scripts/fastmcp_verify.sh --target $TARGET --run-dry-run"
echo "   bash scripts/pipeline_transaction_discovery.sh"
echo "   bash scripts/monitor-combat-readiness.sh"
echo ""
echo " Live broadcast — Mac ONLY:"
echo "   export HEXSTRIKE_TX_LIVE=1"
echo "   bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --live"
echo "════════════════════════════════════════════════════════"
echo " SECURITY: do not export real BOT_PRIVATE_KEY or HEXSTRIKE_TX_LIVE=1 on VPS"
echo "════════════════════════════════════════════════════════"
