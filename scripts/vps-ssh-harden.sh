#!/usr/bin/env bash
# Harden root SSH on HexStrike VPS: install agent pubkey, disable password auth.
#
# Run as root on the VPS (MiroHost web/VNC console if SSH is locked out):
#   curl -fsSL https://raw.githubusercontent.com/banda198565/hexstrike-ai/cursor/vps-ssh-harden-3352/scripts/vps-ssh-harden.sh | bash
# Or paste the offline block from the script footer.
#
# Optional:
#   NEW_ROOT_PASSWORD='...' bash scripts/vps-ssh-harden.sh   # rotate root password before disabling password auth
#   KEEP_PASSWORD_AUTH=1 bash scripts/vps-ssh-harden.sh      # install key only, keep password login
set -euo pipefail

PUBKEY_PRIMARY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOc4+341bbWPywULPF8MTDq9VpaDMT4+TqKLpK4Uo2Gs hexstrike-01@cursor-20260714"
PUBKEY_LEGACY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByufH4aDtJgrm/Udc3Vai4heLmGhT2N4xKdZ5bjZ0DH cursor-cloud-hexstrike"
SSHD_CFG="/etc/ssh/sshd_config"
SSHD_DROPIN_DIR="/etc/ssh/sshd_config.d"
DROPIN="${SSHD_DROPIN_DIR}/99-hexstrike-harden.conf"

log() { echo "[vps-ssh-harden] $*"; }
die() { echo "[vps-ssh-harden] ERROR: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root (MiroHost console / sudo)"

mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

install_key() {
  local key="$1"
  local comment
  comment="$(awk '{print $NF}' <<<"$key")"
  if grep -qF "$key" /root/.ssh/authorized_keys 2>/dev/null; then
    log "key already present: $comment"
  else
    echo "$key" >> /root/.ssh/authorized_keys
    log "installed key: $comment"
  fi
}

install_key "$PUBKEY_PRIMARY"
install_key "$PUBKEY_LEGACY"

if [[ -n "${NEW_ROOT_PASSWORD:-}" ]]; then
  log "rotating root password from NEW_ROOT_PASSWORD"
  echo "root:${NEW_ROOT_PASSWORD}" | chpasswd
else
  log "NEW_ROOT_PASSWORD unset — root password left unchanged"
fi

# Prefer drop-in so package upgrades do not clobber harden settings
mkdir -p "$SSHD_DROPIN_DIR"
if [[ "${KEEP_PASSWORD_AUTH:-0}" == "1" ]]; then
  cat >"$DROPIN" <<'EOF'
# HexStrike: key auth enabled; password auth kept temporarily
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication no
EOF
  log "KEEP_PASSWORD_AUTH=1 — password login still enabled"
else
  cat >"$DROPIN" <<'EOF'
# HexStrike: key-only root SSH
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
EOF
  # Neutralize conflicting PasswordAuthentication yes in main config if present
  if grep -qE '^[#[:space:]]*PasswordAuthentication[[:space:]]+' "$SSHD_CFG" 2>/dev/null; then
    sed -i -E 's/^[#[:space:]]*PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CFG"
  fi
  if grep -qE '^[#[:space:]]*PermitRootLogin[[:space:]]+' "$SSHD_CFG" 2>/dev/null; then
    sed -i -E 's/^[#[:space:]]*PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD_CFG"
  fi
  log "password authentication disabled (key-only)"
fi

if command -v sshd >/dev/null 2>&1; then
  sshd -t || die "sshd_config validation failed — not restarting ssh"
fi

if systemctl is-active --quiet ssh 2>/dev/null; then
  systemctl reload ssh || systemctl restart ssh
elif systemctl is-active --quiet sshd 2>/dev/null; then
  systemctl reload sshd || systemctl restart sshd
else
  service ssh reload 2>/dev/null || service ssh restart 2>/dev/null || \
    service sshd reload 2>/dev/null || service sshd restart 2>/dev/null || \
    die "could not reload ssh/sshd"
fi

log "sshd reloaded"
log "authorized_keys entries: $(wc -l </root/.ssh/authorized_keys)"
log "DONE — verify from agent: ssh -i hexstrike_vps_key root@78.27.235.70"
echo "fingerprint expected: SHA256:78K9fBhhOGmuThLoir5QsfVIn3nL970N1/q/aPN5eyQ"
