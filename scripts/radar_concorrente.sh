#!/usr/bin/env bash
# Radar de concorrente (2026-08-21) — ingestão frequente do observer + resolução
# dos links divulgados nos grupos observados.
#
# Por que separado do `market_intel_daily.sh`: aquele roda 1x/dia às 22h, e foi
# medido em 2026-08-21 que essa cadência tem dois custos. O buffer do
# evolution_adapter é janela rolante de 24h com teto de 300 mensagens por grupo,
# então grupo movimentado perde mensagem entre uma coleta e outra; e a oferta
# chegava ao banco com até 24h de atraso, tempo em que a campanha de cupom que a
# sustenta já acabou. Aqui a coleta roda a cada 20 min e a análise/relatório
# continua diária, no horário de sempre.
#
# `resolve_competitor_links` abre um link por vez, com pausa de 2-4,5s entre
# eles — o mesmo intervalo que o scraper usa nas páginas de categoria.
set -euo pipefail

cd "$(dirname "$0")/.."

# Interpretador do venv, não o `python3` do PATH: sob `systemd --user` o PATH é
# mínimo e o python do sistema não tem as dependências de scraping (bs4,
# curl_cffi). O `market_intel_daily.sh` sobrevive com `python3` porque nenhum
# comando dele importa o scraper.
PYTHON="$(pwd)/.venv/bin/python3"

"$PYTHON" manage.py collect_whatsapp_offer_groups --timeout "${WA_OBSERVER_TIMEOUT_SECONDS:-30}"
"$PYTHON" manage.py resolve_competitor_links --limit "${COMPETITOR_RADAR_LIMIT:-20}"
