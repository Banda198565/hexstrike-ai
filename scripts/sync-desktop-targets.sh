#!/usr/bin/env bash
# Sync macOS Desktop "тест ЦЕЛИ" → workspace/VPS target pool for Samson ingest.
#
# Usage (on Mac — push to VPS):
#   scp -r ~/Desktop/тест\ ЦЕЛИ user@vps:/workspace/data/pentest/targets/
#
# Usage (local copy into repo):
#   bash scripts/sync-desktop-targets.sh ~/Desktop/тест\ ЦЕЛИ
#
# Usage (already on VPS with env):
#   export SAMSON_TARGETS_DIR=/workspace/data/pentest/targets
#   bash scripts/sync-desktop-targets.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${SAMSON_TARGETS_DIR:-$ROOT/data/pentest/targets}"
SRC="${1:-}"

mkdir -p "$DEST"

if [[ -n "$SRC" ]]; then
  if [[ ! -d "$SRC" ]]; then
    echo "ERROR: source not found: $SRC" >&2
    exit 1
  fi
  echo "Sync $SRC → $DEST"
  rsync -a --delete "$SRC/" "$DEST/"
else
  DESKTOP="$HOME/Desktop/тест ЦЕЛИ"
  if [[ -d "$DESKTOP" ]]; then
    echo "Sync $DESKTOP → $DEST"
    rsync -a --delete "$DESKTOP/" "$DEST/"
  elif [[ -d "$DEST" ]] && [[ -n "$(ls -A "$DEST" 2>/dev/null)" ]]; then
    echo "Using existing pool: $DEST"
  else
    echo "No source. Options:" >&2
    echo "  1) bash scripts/sync-desktop-targets.sh ~/Desktop/тест\ ЦЕЛИ" >&2
    echo "  2) scp -r ~/Desktop/тест\ ЦЕЛИ user@host:$DEST" >&2
    echo "  3) export SAMSON_TARGETS_DIR=/path/to/targets" >&2
    exit 1
  fi
fi

export SAMSON_TARGETS_DIR="$DEST"
echo "--- Ingest dry-run ---"
python3 "$ROOT/scripts/ingest-target-pool.py" --root "$DEST" --dry-run
echo ""
echo "Full ingest (live probe):"
echo "  SAMSON_TARGETS_DIR=$DEST python3 scripts/ingest-target-pool.py --root $DEST"
