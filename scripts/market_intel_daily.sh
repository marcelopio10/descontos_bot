#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 manage.py collect_whatsapp_offer_groups --timeout "${WA_OBSERVER_TIMEOUT_SECONDS:-30}"
python3 manage.py analyze_whatsapp_offer_groups --days "${MARKET_INTEL_DAYS:-1}"
python3 manage.py publish_market_intel_report --output "${MARKET_INTEL_OUTPUT:-site/market-intel.json}"

# Aderência aos grupos observados (2026-08-21). Só escreve no log, não publica
# nada: serve para ter a série no tempo — taxa de eco, cobertura das ofertas de
# consenso e latência do radar, dia a dia, em logs/market-intel.log.
python3 manage.py analyze_group_adherence --days 1
python3 manage.py analyze_group_adherence --days 7
