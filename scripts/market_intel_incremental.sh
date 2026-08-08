#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
cd "$PROJECT_DIR"
exec "$PYTHON_BIN" manage.py process_market_intel_incremental --timeout "${WA_OBSERVER_TIMEOUT_SECONDS:-30}"
