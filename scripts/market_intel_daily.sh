#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 manage.py collect_whatsapp_offer_groups --timeout "${WA_OBSERVER_TIMEOUT_SECONDS:-30}"
python3 manage.py analyze_whatsapp_offer_groups --days "${MARKET_INTEL_DAYS:-1}"
python3 manage.py publish_market_intel_report --output "${MARKET_INTEL_OUTPUT:-site/market-intel.json}"
