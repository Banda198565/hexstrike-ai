#!/usr/bin/env bash
# bootstrap-new-vps.sh — first-time HexStrike VPS setup from YOUR Mac/iMac.
#
# Ideal path when cloud agents cannot SSH (KEX reset / fail2ban):
#   A) This script from Mac (password login), OR
#   B) Paste onbox script in hoster VNC/console:
#        curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/master/scripts/bootstrap-new-vps-onbox.sh | bash
#
# Usage (password via env — never argv / never git):
#   read -s VPS_PASSWORD; export VPS_PASSWORD; echo
#   bash scripts/bootstrap-new-vps.sh root@78.27.235.70
#
# Defaults (first-day safe):
#   SKIP_PASSWD_ROTATE=1   — do NOT change root password
#   KEEP_PASSWORD_AUTH=1   — keep password login until you harden later
#
# Optional overrides:
#   SKIP_PASSWD_ROTATE=0   — rotate root password (prints once)
#   KEEP_PASSWORD_AUTH=0   — key-only SSH after key install
#   SKIP_OSINT=1           — skip Shodan/Arkham smoke
#   LOCAL_ENV=/path/.env   — source of secrets to scp
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
KEY="${HEXSTRIKE_VPS_KEY:-$HOME/.ssh/hexstrike_vps}"
LOCAL_ENV="${LOCAL_ENV:-$ROOT/.env}"
REPO_URL="${REPO_URL:-https://github.com/Banda198565/hexstrike-ai.git}"
REMOTE_DIR="${REMOTE_DIR:-/root/hexstrike-ai}"
BRANCH="${BOOTSTRAP_BRANCH:-master}"

# First-day defaults (operator asked: continue without password change)
SKIP_PASSWD_ROTATE="${SKIP_PASSWD_ROTATE:-1}"
KEEP_PASSWORD_AUTH="${KEEP_PASSWORD_AUTH:-1}"
SKIP_OSINT="${SKIP_OSINT:-0}"

log() { echo "[bootstrap-vps] $*"; }
die() { echo "[bootstrap-vps] ERROR: $*" >&2; exit 1; }

[[ -n "$TARGET" ]] || die "usage: bash scripts/bootstrap-new-vps.sh root@HOST"
[[ "$TARGET" == *@* ]] || die "TARGET must look like root@IP"
command -v ssh >/dev/null || die "ssh required"
command -v sshpass >/dev/null || die "sshpass required (brew install hudochenkov/sshpass/sshpass || apt install sshpass)"

if [[ -z "${VPS_PASSWORD:-}" ]]; then
  die "Set VPS_PASSWORD (read -s VPS_PASSWORD; export VPS_PASSWORD)"
fi
export SSHPASS="$VPS_PASSWORD"

SSH_BASE=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 -o ServerAliveInterval=5)
SSHP=(sshpass -e "${SSH_BASE[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)

# ── Step 1: password login ──────────────────────────────────────
log "Step 1/7: password login → $TARGET"
if ! "${SSHP[@]}" "$TARGET" 'echo LOGIN_OK; uname -a; whoami'; then
  cat <<'EOF' >&2

[bootstrap-vps] SSH password login failed (or Connection reset during KEX).

Fallback — open hoster VNC/console as root and run:

  curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/master/scripts/bootstrap-new-vps-onbox.sh | bash

Then from Mac:
  ssh-copy-id -i ~/.ssh/hexstrike_vps.pub root@HOST
  scp .env root@HOST:/root/hexstrike-ai/.env

EOF
  die "SSH login failed"
fi

# ── Step 2: optional password rotate (OFF by default) ───────────
if [[ "$SKIP_PASSWD_ROTATE" == "1" ]]; then
  log "Step 2/7: SKIP password rotate (SKIP_PASSWD_ROTATE=1)"
else
  NEW_PASS="$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(28)))')"
  log "Step 2/7: rotating root password (printed ONCE)"
  "${SSHP[@]}" "$TARGET" "echo 'root:${NEW_PASS}' | chpasswd && echo PASSWD_OK"
  echo
  echo "========== NEW ROOT PASSWORD (save now) =========="
  echo "$NEW_PASS"
  echo "=================================================="
  echo
  export SSHPASS="$NEW_PASS"
fi

# ── Step 3: local key + install pubkey ──────────────────────────
log "Step 3/7: install ed25519 pubkey"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "hexstrike-vps-$(whoami)@$(hostname)-$(date +%Y%m%d)"
fi
chmod 600 "$KEY" "${KEY}.pub"
PUB="$(cat "${KEY}.pub")"
"${SSHP[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qxF '$PUB' /root/.ssh/authorized_keys || echo '$PUB' >> /root/.ssh/authorized_keys
echo KEY_INSTALLED
EOF

SSHK=(ssh -i "$KEY" -o IdentitiesOnly=yes "${SSH_BASE[@]}")
SCPK=(scp -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
"${SSHK[@]}" "$TARGET" 'echo KEY_LOGIN_OK' || die "key login failed"

# ── Step 4: upload onbox script + run (single source of truth) ──
log "Step 4/7: remote onbox bootstrap (apt/clone/venv/harden)"
"${SCPK[@]}" "$ROOT/scripts/bootstrap-new-vps-onbox.sh" "$TARGET:/tmp/bootstrap-new-vps-onbox.sh"
"${SSHK[@]}" "$TARGET" \
  "KEEP_PASSWORD_AUTH=$KEEP_PASSWORD_AUTH SKIP_OSINT=1 REPO_URL='$REPO_URL' REMOTE_DIR='$REMOTE_DIR' BOOTSTRAP_BRANCH='$BRANCH' bash /tmp/bootstrap-new-vps-onbox.sh"

# ── Step 5: sync .env ───────────────────────────────────────────
log "Step 5/7: sync .env (values not printed)"
if [[ -f "$LOCAL_ENV" ]]; then
  "${SCPK[@]}" "$LOCAL_ENV" "$TARGET:$REMOTE_DIR/.env"
  "${SSHK[@]}" "$TARGET" "chmod 600 '$REMOTE_DIR/.env' && echo ENV_SYNC_OK"
else
  log "WARN: $LOCAL_ENV missing — fill keys on VPS later"
fi

# ── Step 6: OSINT smoke ─────────────────────────────────────────
if [[ "$SKIP_OSINT" != "1" ]]; then
  log "Step 6/7: OSINT smoke"
  "${SSHK[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
cd '$REMOTE_DIR'
set -a
# shellcheck disable=SC1091
[[ -f .env ]] && source .env
set +a
# shellcheck disable=SC1091
source hexstrike-env/bin/activate
export PYTHONPATH='$REMOTE_DIR:$REMOTE_DIR/src:\${PYTHONPATH:-}'
export ARKHAM_API_KEY="\${ARKHAM_API_KEY:-\${SAMSON_ARKHAM_API_KEY:-}}"
mkdir -p artifacts docs/recon
[[ -n "\${SHODAN_API_KEY:-}" ]] && bash scripts/run-ru-shodan-recon.sh || true
[[ -n "\${SHODAN_API_KEY:-}" ]] && bash scripts/run-kz-shodan-recon.sh || true
[[ -n "\${ARKHAM_API_KEY:-}" ]] && bash scripts/arkham-probe.sh || true
echo OSINT_SMOKE_DONE
EOF
else
  log "Step 6/7: SKIP OSINT (SKIP_OSINT=1)"
fi

# ── Step 7: verify ──────────────────────────────────────────────
log "Step 7/7: verify"
"${SSHK[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
cd '$REMOTE_DIR'
test -d hexstrike-env
test -f artifacts/vps-bootstrap-status.json && cat artifacts/vps-bootstrap-status.json || true
# shellcheck disable=SC1091
source hexstrike-env/bin/activate
python3 -c 'import sys; print("python", sys.version.split()[0])'
echo VERIFY_OK
EOF

cat <<EOF

[bootstrap-vps] DONE (ideal first-day profile)
  ssh -i $KEY $TARGET
  cd $REMOTE_DIR

  Defaults used:
    SKIP_PASSWD_ROTATE=$SKIP_PASSWD_ROTATE
    KEEP_PASSWORD_AUTH=$KEEP_PASSWORD_AUTH

  Later (key-only harden):
    ssh -i $KEY $TARGET 'cd $REMOTE_DIR && KEEP_PASSWORD_AUTH=0 bash scripts/vps-ssh-harden.sh'

EOF
