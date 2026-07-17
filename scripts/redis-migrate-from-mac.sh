#!/usr/bin/env bash
# Run on Mac (source Redis). Dumps RDB and copies to HexStrike VPS over SSH.
#
# Usage:
#   REDIS_PASSWORD='your-mac-redis-password' bash scripts/redis-migrate-from-mac.sh
#
# Requires: redis-cli on Mac, working `ssh hexstrike-vps` (key auth).
set -euo pipefail

VPS_HOST="${VPS_HOST:-hexstrike-vps}"
LOCAL_RDB="${LOCAL_RDB:-/tmp/hexstrike_migration.rdb}"
REMOTE_RDB="${REMOTE_RDB:-/tmp/hexstrike_migration.rdb}"
AUTH="${REDISCLI_AUTH:-${REDIS_PASSWORD:-}}"

if [[ -z "$AUTH" ]]; then
  echo "[migrate] ERROR: set REDIS_PASSWORD or REDISCLI_AUTH for the Mac Redis instance" >&2
  echo "  example: REDIS_PASSWORD='...' bash scripts/redis-migrate-from-mac.sh" >&2
  exit 1
fi

export REDISCLI_AUTH="$AUTH"

echo "[migrate] dumping Mac redis -> $LOCAL_RDB"
redis-cli --rdb "$LOCAL_RDB"
ls -la "$LOCAL_RDB"

echo "[migrate] copying to ${VPS_HOST}:${REMOTE_RDB}"
scp -O "$LOCAL_RDB" "${VPS_HOST}:${REMOTE_RDB}"
ssh "$VPS_HOST" "ls -la '${REMOTE_RDB}' && file '${REMOTE_RDB}'"

cat <<'EOF'
[migrate] DONE
Next on VPS (review first — this replaces Redis data):
  sudo systemctl stop redis-server
  sudo cp /tmp/hexstrike_migration.rdb /var/lib/redis/dump.rdb
  sudo chown redis:redis /var/lib/redis/dump.rdb
  sudo systemctl start redis-server
EOF
