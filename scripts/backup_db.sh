#!/usr/bin/env bash
# descontos.bot - Backup diário do SQLite via API .backup (seguro com o processo rodando)
#
# Dois destinos, de propósito:
#   data/backups/  cópia crua, últimos 7. Protege contra corrupção do banco (já
#                  aconteceu em 19/07) e restaura sem descompactar.
#   OneDrive       cópia gzip, últimos 14. Protege contra perda do disco, que é
#                  o risco real: a operação inteira vive neste notebook.
#                  Comprimido porque o banco passa de 110 MB e o sync diário do
#                  OneDrive não deve carregar isso cru.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${REPO_DIR}/data/descontos_bot.db"
BACKUP_DIR="${REPO_DIR}/data/backups"
KEEP=7

OFFSITE_DIR="${DESCONTOS_BACKUP_OFFSITE_DIR:-/mnt/c/Users/marce/OneDrive/Backups/descontos.bot}"
OFFSITE_KEEP=14

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

# --- Cópia comprimida fora do disco local ------------------------------------
# Falha aqui não invalida o backup local, que já está feito: o script avisa e
# sai com erro para o systemd registrar, mas a cópia crua permanece válida.
if ! mkdir -p "${OFFSITE_DIR}" 2>/dev/null; then
    echo "AVISO: destino offsite indisponível (${OFFSITE_DIR}); backup local mantido." >&2
    exit 1
fi

OFFSITE_DEST="${OFFSITE_DIR}/descontos_bot.${TS}.bak.db.gz"
if gzip -c "${DEST}" > "${OFFSITE_DEST}.partial" 2>/dev/null; then
    # Só promove ao nome final depois de fechar o arquivo, para o OneDrive nunca
    # sincronizar um .gz truncado como se fosse backup bom.
    mv "${OFFSITE_DEST}.partial" "${OFFSITE_DEST}"
    echo "Backup offsite criado: ${OFFSITE_DEST} ($(du -h "${OFFSITE_DEST}" | cut -f1))"
else
    rm -f "${OFFSITE_DEST}.partial"
    echo "AVISO: falha ao comprimir para ${OFFSITE_DEST}; backup local mantido." >&2
    exit 1
fi

OFFSITE_BACKUPS=$(ls -1t "${OFFSITE_DIR}"/descontos_bot.*.bak.db.gz 2>/dev/null || true)
OFFSITE_COUNT=$(echo "${OFFSITE_BACKUPS}" | grep -c . || true)

if [ "${OFFSITE_COUNT}" -gt "${OFFSITE_KEEP}" ]; then
    echo "${OFFSITE_BACKUPS}" | tail -n +"$((OFFSITE_KEEP + 1))" | while read -r OLD; do
        [ -n "${OLD}" ] && rm -f "${OLD}" && echo "Backup offsite antigo removido: ${OLD}"
    done
fi
