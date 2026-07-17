#!/usr/bin/env bash
# bootstrap-new-vps.sh — first-time HexStrike VPS setup from YOUR Mac/iMac.
#
# Cloud agents often get Connection reset during SSH KEX (provider/fail2ban).
# Run this on a machine that can password-login as root.
#
# Usage (never put the password in the command line / git):
#   read -s VPS_PASSWORD; export VPS_PASSWORD; echo
#   bash scripts/bootstrap-new-vps.sh root@78.27.235.70
#
# Optional:
#   VPS_PASSWORD=... LOCAL_ENV=/path/to/.env bash scripts/bootstrap-new-vps.sh root@HOST
#   SKIP_PASSWD_ROTATE=1 ...  # do NOT change root password (default: rotate — chat passwords are burned)
#   SKIP_OSINT=1 ...          # skip Shodan/Arkham smoke after install
#   KEEP_PASSWORD_AUTH=1 ...  # do not disable password auth yet
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
KEY="${HEXSTRIKE_VPS_KEY:-$HOME/.ssh/hexstrike_vps}"
LOCAL_ENV="${LOCAL_ENV:-$ROOT/.env}"
REPO_URL="${REPO_URL:-https://github.com/Banda198565/hexstrike-ai.git}"
REMOTE_DIR="${REMOTE_DIR:-/root/hexstrike-ai}"

log() { echo "[bootstrap-vps] $*"; }
die() { echo "[bootstrap-vps] ERROR: $*" >&2; exit 1; }

[[ -n "$TARGET" ]] || die "usage: bash scripts/bootstrap-new-vps.sh root@HOST"
[[ "$TARGET" == *@* ]] || die "TARGET must look like root@IP"
command -v ssh >/dev/null || die "ssh required"
command -v sshpass >/dev/null || die "sshpass required (brew install sshpass / apt install sshpass)"

if [[ -z "${VPS_PASSWORD:-}" ]]; then
  die "Set VPS_PASSWORD in the environment (use: read -s VPS_PASSWORD; export VPS_PASSWORD)"
fi
export SSHPASS="$VPS_PASSWORD"

SSH_BASE=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
SSHP=(sshpass -e "${SSH_BASE[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)
SCPP=(sshpass -e scp -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password -o PubkeyAuthentication=no)

# ── Step 1: password login ──────────────────────────────────────
log "Step 1: password login → $TARGET"
"${SSHP[@]}" "$TARGET" 'echo LOGIN_OK; uname -a; whoami' || die "SSH password login failed"

# ── Step 2: optional root password rotate ───────────────────────
if [[ "${SKIP_PASSWD_ROTATE:-0}" == "1" ]]; then
  log "Step 2: SKIP password rotate (SKIP_PASSWD_ROTATE=1)"
else
  NEW_PASS="$(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(28)))
PY
)"
  log "Step 2: rotating root password (new password printed ONCE below)"
  "${SSHP[@]}" "$TARGET" "echo 'root:${NEW_PASS}' | chpasswd && echo PASSWD_OK"
  cat <<EOF

========== SAVE THIS ROOT PASSWORD (password auth may be disabled later) ==========
${NEW_PASS}
====================================================================================

EOF
  export SSHPASS="$NEW_PASS"
  VPS_PASSWORD="$NEW_PASS"
fi

# ── Step 3: SSH key ─────────────────────────────────────────────
log "Step 3: ensure local key + install pubkey on VPS"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "hexstrike-vps-$(whoami)@$(hostname)-$(date +%Y%m%d)"
fi
chmod 600 "$KEY" "${KEY}.pub"
PUB="$(cat "${KEY}.pub")"
"${SSHP[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -qxF '$PUB' /root/.ssh/authorized_keys || echo '$PUB' >> /root/.ssh/authorized_keys
echo KEY_INSTALLED
EOF

# Switch to key auth for the rest
SSHK=(ssh -i "$KEY" -o IdentitiesOnly=yes "${SSH_BASE[@]}")
SCPK=(scp -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
"${SSHK[@]}" "$TARGET" 'echo KEY_LOGIN_OK' || die "key login failed after install"

# Optional harden (disable password) unless KEEP_PASSWORD_AUTH=1
if [[ "${KEEP_PASSWORD_AUTH:-0}" != "1" ]]; then
  log "Disabling PasswordAuthentication (KEEP_PASSWORD_AUTH=1 to skip)"
  "${SSHK[@]}" "$TARGET" 'bash -s' <<'EOF'
set -euo pipefail
mkdir -p /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/00-hexstrike-bootstrap.conf <<'CFG'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
CFG
if [[ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ]]; then
  sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf || true
fi
sshd -t
systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload
echo HARDEN_OK
EOF
fi

# ── Step 4: packages + clone ─────────────────────────────────────
log "Step 4: apt + clone repo"
"${SSHK[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl ca-certificates
if [[ -d '$REMOTE_DIR/.git' ]]; then
  cd '$REMOTE_DIR' && git fetch origin && git checkout master && git pull --ff-only origin master
else
  rm -rf '$REMOTE_DIR'
  git clone '$REPO_URL' '$REMOTE_DIR'
fi
cd '$REMOTE_DIR'
python3 -m venv hexstrike-env
# shellcheck disable=SC1091
source hexstrike-env/bin/activate
pip install -q --upgrade pip
if [[ -f requirements-samson.txt ]]; then
  pip install -q -r requirements-samson.txt
elif [[ -f requirements.txt ]]; then
  pip install -q -r requirements.txt
fi
echo CLONE_OK
EOF

# ── Step 5: .env ────────────────────────────────────────────────
log "Step 5: sync .env (secrets not printed)"
if [[ -f "$LOCAL_ENV" ]]; then
  "${SCPK[@]}" "$LOCAL_ENV" "$TARGET:$REMOTE_DIR/.env"
  "${SSHK[@]}" "$TARGET" "chmod 600 '$REMOTE_DIR/.env' && echo ENV_SYNC_OK"
else
  log "WARN: $LOCAL_ENV missing — create .env on VPS manually"
fi

# ── Step 6: OSINT smoke (optional) ──────────────────────────────
if [[ "${SKIP_OSINT:-0}" != "1" ]]; then
  log "Step 6: OSINT smoke (RU/KZ/Arkham) — may take a few minutes"
  "${SSHK[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
cd '$REMOTE_DIR'
set -a
# shellcheck disable=SC1091
source .env
set +a
# shellcheck disable=SC1091
source hexstrike-env/bin/activate
export PYTHONPATH='$REMOTE_DIR:$REMOTE_DIR/src:\${PYTHONPATH:-}'
mkdir -p artifacts docs/recon
if [[ -x scripts/run-ru-shodan-recon.sh ]]; then bash scripts/run-ru-shodan-recon.sh || true; fi
if [[ -x scripts/run-kz-shodan-recon.sh ]]; then bash scripts/run-kz-shodan-recon.sh || true; fi
if [[ -x scripts/arkham-probe.sh ]]; then bash scripts/arkham-probe.sh || true; fi
echo OSINT_SMOKE_DONE
EOF
else
  log "Step 6 skipped (SKIP_OSINT=1)"
fi

cat <<EOF

[bootstrap-vps] DONE

Login:
  ssh -i $KEY $TARGET

Repo:
  $REMOTE_DIR

Remember:
  - Password from chat is BURNED — use the new password printed above (or key-only).
  - Do not commit .env
  - From this Mac, prefer: ssh -i $KEY $TARGET

EOF
