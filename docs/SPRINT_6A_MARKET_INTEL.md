# Sprint 6A — Market Intelligence WhatsApp

## Objetivo

Coletar e analisar padrões agregados de grupos WhatsApp de ofertas para melhorar curadoria, copy, planejamento editorial e scrapers do descontos.bot.

A funcionalidade é inteligência editorial, não fonte de ofertas publicáveis.

## Segurança e privacidade

- Observer desligado por padrão: `WA_OBSERVER_ENABLED=false`.
- Apenas grupos em `WA_OBSERVER_GROUP_JIDS` são considerados.
- O serviço não envia, reage nem interage com grupos monitorados.
- Remetente é salvo apenas como hash SHA-256.
- Relatórios e JSON público não expõem hash de remetente nem URLs observadas.
- Links de terceiros nunca entram no pipeline de publicação.

## Variáveis

```env
WA_OBSERVER_ENABLED=false
WA_OBSERVER_GROUP_JIDS=1203xxx@g.us,1203yyy@g.us
WA_OBSERVER_LOOKBACK_HOURS=24
WA_OBSERVER_MAX_MESSAGES_PER_GROUP=300
WA_OBSERVER_SENDER_HASH_SALT=<definir localmente>
```

## Endpoints wa_service

```http
GET /observer/groups
POST /observer/collect
GET /debug/last-messages
```

`/observer/groups` lista somente grupos allowlisted quando o observer está ligado.

`/observer/collect` retorna mensagens normalizadas já filtradas por allowlist e janela.

## Pipeline Django

```bash
python3 manage.py collect_whatsapp_offer_groups --timeout 30
python3 manage.py analyze_whatsapp_offer_groups --days 1
python3 manage.py publish_market_intel_report --output site/market-intel.json
```

Script equivalente:

```bash
scripts/market_intel_daily.sh
```

## Saídas

- Banco: `ObservedWhatsAppGroup`, `ObservedWhatsAppMessage`, `MarketIntelDailyReport`.
- JSON: `site/market-intel.json`.
- Página operacional: `site/inteligencia.html`.

## Aplicação dos insights

Os primeiros relatórios devem alimentar recomendações manuais para:

- termos e categorias dos scrapers;
- ajustes no quality score;
- variações de copy;
- pautas editoriais por faixa de preço/categoria/cupom.

Não aplicar mudanças automáticas no score/copy/scrapers antes de validar os relatórios iniciais.
