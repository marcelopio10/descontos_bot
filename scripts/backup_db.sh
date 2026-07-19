#!/usr/bin/env bash
# descontos.bot - Backup diário do SQLite via API .backup (seguro com o processo rodando)
# Mantém os últimos 7 backups em data/backups/.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${REPO_DIR}/data/descontos_bot.db"
BACKUP_DIR="${REPO_DIR}/data/backups"
KEEP=7

mkdir -p "${BACKUP_DIR}"

if [ ! -f "${DB_PATH}" ]; then
    echo "ERRO: banco não encontrado em ${DB_PATH}" >&2
    exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
DEST="${BACKUP_DIR}/descontos_bot.${TS}.bak.db"

PYTHON_BIN="${REPO_DIR}/.venv/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

"${PYTHON_BIN}" - "${DB_PATH}" "${DEST}" <<'PY'
import sqlite3
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

echo "Backup criado: ${DEST}"

# Mantém apenas os últimos $KEEP backups
BACKUPS=$(ls -1t "${BACKUP_DIR}"/descontos_bot.*.bak.db 2>/dev/null || true)
COUNT=$(echo "${BACKUPS}" | grep -c . || true)

if [ "${COUNT}" -gt "${KEEP}" ]; then
    echo "${BACKUPS}" | tail -n +"$((KEEP + 1))" | while read -r OLD; do
        [ -n "${OLD}" ] && rm -f "${OLD}" && echo "Backup antigo removido: ${OLD}"
    done
fi
