#!/usr/bin/env bash
# setup-rag-hdd.sh — create RAG storage on external HDD and wire symlink + .env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HDD_NAME="${HEXSTRIKE_HDD_NAME:-Eva}"
HDD_MOUNT="${HEXSTRIKE_HDD_MOUNT:-/Volumes/${HDD_NAME}}"
RAG_ROOT="${RAG_STORAGE_ROOT:-${RAG_STORAGE_PATH:-${HDD_MOUNT}/hexstrike-rag-data}}"
SYMLINK="${ROOT}/artifacts/rag-storage"
ENV_FILE="${ROOT}/.env"

log() { echo "[rag-setup] $*"; }
die() { echo "[rag-setup] ERROR: $*" >&2; exit 1; }

[[ -d "${HDD_MOUNT}" ]] || die "HDD not mounted: ${HDD_MOUNT}"
[[ -w "${HDD_MOUNT}" ]] || die "HDD not writable: ${HDD_MOUNT}"

log "Creating RAG directory tree on ${RAG_ROOT}..."
mkdir -p \
  "${RAG_ROOT}/vector-store/lancedb" \
  "${RAG_ROOT}/embeddings-cache" \
  "${RAG_ROOT}/raw-docs"

log "Linking ${SYMLINK} -> ${RAG_ROOT}"
mkdir -p "${ROOT}/artifacts"
if [[ -L "${SYMLINK}" ]]; then
  CURRENT="$(readlink "${SYMLINK}")"
  if [[ "${CURRENT}" == "${RAG_ROOT}" ]]; then
    log "Symlink already correct"
  else
    rm "${SYMLINK}"
    ln -s "${RAG_ROOT}" "${SYMLINK}"
  fi
elif [[ -d "${SYMLINK}" && ! -L "${SYMLINK}" ]]; then
  log "Moving existing local rag-storage to raw-docs backup..."
  mkdir -p "${RAG_ROOT}/raw-docs/local-migration"
  cp -R "${SYMLINK}/." "${RAG_ROOT}/raw-docs/local-migration/" 2>/dev/null || true
  rm -rf "${SYMLINK}"
  ln -s "${RAG_ROOT}" "${SYMLINK}"
else
  ln -s "${RAG_ROOT}" "${SYMLINK}"
fi

set_env() {
  local key="$1" val="$2"
  if [[ -f "${ENV_FILE}" ]] && grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "${ENV_FILE}"
  else
    echo "${key}=${val}" >> "${ENV_FILE}"
  fi
}

touch "${ENV_FILE}"
set_env "RAG_STORAGE_ROOT" "${RAG_ROOT}"
set_env "RAG_STORAGE_PATH" "${RAG_ROOT}"
set_env "DB_TYPE" "lancedb"
set_env "RAG_BATCH_SIZE" "16"
set_env "RAG_NUM_WORKERS" "4"
set_env "HEXSTRIKE_EVA_MOUNT" "${HDD_MOUNT}"

export RAG_STORAGE_ROOT="${RAG_ROOT}"
export RAG_STORAGE_PATH="${RAG_ROOT}"

log "Verifying RAG core..."
if [[ -x "${ROOT}/rag-env/bin/python" ]]; then
  PY="${ROOT}/rag-env/bin/python"
elif [[ -x "${ROOT}/hexstrike-env/bin/python" ]]; then
  PY="${ROOT}/hexstrike-env/bin/python"
else
  PY="python3"
fi

"${PY}" "${ROOT}/scripts/rag_core.py" --status || die "rag_core status failed"

echo ""
echo "=========================================="
echo "  RAG HDD storage ready"
echo "=========================================="
echo "  Root:     ${RAG_ROOT}"
echo "  Symlink:  ${SYMLINK} -> ${RAG_ROOT}"
echo "  Index:    ${RAG_ROOT}/vector-store/lancedb/"
echo "  Cache:    ${RAG_ROOT}/embeddings-cache/"
echo "  Raw docs: ${RAG_ROOT}/raw-docs/"
echo ""
echo "  Index artifacts:"
echo "    python3 scripts/rag_core.py --index-all artifacts/"
echo "  Search:"
echo "    python3 scripts/rag_core.py --search 'hot wallet rhino bridge'"
echo ""
