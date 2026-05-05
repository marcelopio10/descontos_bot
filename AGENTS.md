# Regras para agentes neste repositório

## Stack obrigatória

- Use Python 3.11+ com Django 6.0.4, Node.js 20 LTS, SQLite e Baileys.
- Use SQLite exclusivamente em `data/descontos_bot.db`.
- Mantenha WAL e `foreign_keys=ON` no SQLite.
- Preserve o serviço existente em `wa_service/` quando portar funcionalidades.

## PROIBIDO

- PROIBIDO Docker, Dockerfile, docker-compose ou qualquer runtime equivalente.
- PROIBIDO FastAPI, Uvicorn, SQLAlchemy e Jinja2.
- PROIBIDO banco que não seja SQLite.
- PROIBIDO commitar `.env`, sessões WhatsApp, sessões Instagram, bancos SQLite ou logs locais.
- PROIBIDO criar suíte de testes automatizados como entregável do MVP.

## Código e idioma

- Identificadores, nomes de arquivos, classes, funções e variáveis em inglês.
- UI, `verbose_name`, `verbose_name_plural`, mensagens ao operador e documentação operacional em pt-BR.
- Python com PEP-8, indentação de 4 espaços e aspas simples.
- TypeScript com indentação de 2 espaços e aspas simples.

## Invariantes de produto

- Toda tabela de domínio herda `apps._base.models.TimestampedModel`.
- `Delivery` deve manter `UNIQUE (offer_id, social_channel_id)` quando for implementado.
- A janela de silêncio 00:00-06:00 BRT deve bloquear qualquer distribuição.
- Credenciais ficam em `.env`, nunca em código ou banco em texto claro.
- Scrapers usam sessão HTTP persistente, headers realistas, delays conservadores e detecção de CAPTCHA.

## Verificação mínima antes de entregar

- Rode `python3 manage.py check`.
- Rode `python3 manage.py makemigrations --dry-run` quando houver models.
- Rode os comandos de DoP do sprint no PRD.
- Confira `docs/CHECKLIST_PRE_MERGE.md`.
