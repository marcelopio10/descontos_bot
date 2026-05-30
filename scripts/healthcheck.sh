#!/usr/bin/env bash
# Healthcheck do descontos.bot: falha se o último ciclo do run_bot
# for mais antigo que MAX_AGE_HOURS (default 4h).
#
# Uso:
#   bash scripts/healthcheck.sh                 # usa MAX_AGE_HOURS=4
#   MAX_AGE_HOURS=2 bash scripts/healthcheck.sh
#
# Exit codes:
#   0 = saudável
#   1 = arquivo ausente (bot nunca rodou ou data/ foi removido)
#   2 = ciclo antigo demais

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEALTH_FILE="${SCRIPT_DIR}/../data/last_cycle.txt"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-4}"

if [[ ! -f "$HEALTH_FILE" ]]; then
  echo "FAIL: arquivo de healthcheck ausente: $HEALTH_FILE"
  exit 1
fi

last_iso="$(tr -d '[:space:]' < "$HEALTH_FILE")"
if [[ -z "$last_iso" ]]; then
  echo "FAIL: arquivo de healthcheck vazio"
  exit 1
fi

last_epoch="$(date -d "$last_iso" +%s 2>/dev/null || echo 0)"
if [[ "$last_epoch" -eq 0 ]]; then
  echo "FAIL: timestamp inválido em $HEALTH_FILE: $last_iso"
  exit 1
fi

now_epoch="$(date +%s)"
age_seconds=$((now_epoch - last_epoch))
max_seconds=$((MAX_AGE_HOURS * 3600))

if [[ "$age_seconds" -gt "$max_seconds" ]]; then
  age_hours=$((age_seconds / 3600))
  echo "FAIL: último ciclo há ${age_hours}h (limite: ${MAX_AGE_HOURS}h). Última execução: $last_iso"
  exit 2
fi

age_minutes=$((age_seconds / 60))
echo "OK: último ciclo há ${age_minutes}min ($last_iso)"
exit 0
