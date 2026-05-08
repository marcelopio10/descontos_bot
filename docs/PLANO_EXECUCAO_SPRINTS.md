# Plano de Execução em Sprints — descontos.bot

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to execute sprint tasks step by step. Do not create Docker assets, do not add FastAPI/Uvicorn/SQLAlchemy/Jinja2, and do not create an automated test suite as MVP deliverable.

## Objetivo

Executar o PRD do `descontos.bot` em sprints curtas para um PO humano e dois agentes de IA, entregando primeiro um MVP local funcional com Django, SQLite e WhatsApp.

## Papéis

### PO humano

- Prioriza sprint e aceita entregas.
- Valida operação real do WhatsApp.
- Fornece credenciais em `.env`.
- Decide quando sair de `dry_run`.
- Revisa mensagens enviadas e qualidade das ofertas.

### Agente IA 1 — Backend/Django

- Apps Django.
- Models, migrations e Admin.
- Normalização, seleção e orquestração.
- SQLite, WAL e `foreign_keys=ON`.

### Agente IA 2 — Integrações/Scraping/WhatsApp

- Adaptação dos scrapers existentes.
- Contrato com `wa_service/`.
- Dry run, logs e validação operacional.
- Documentação de execução local.

## Cadência

- Sprint curta de 1 a 2 dias.
- Cada sprint termina com demonstração local.
- Nenhuma sprint pode encerrar sem DoP executado.
- Não versionar `.env`, banco SQLite, sessões WhatsApp, sessões Instagram ou logs locais.

## Definition of Done Global

Executar antes de entregar qualquer sprint:

```bash
python3 manage.py check
```

Se houver alteração em models:

```bash
python3 manage.py makemigrations --dry-run
```

Se houver alteração em `wa_service/` e a suíte existente estiver disponível:

```bash
cd wa_service
npm test
```

Também conferir:

```text
docs/CHECKLIST_PRE_MERGE.md
```

Se o checklist ainda não existir, criá-lo na Sprint 0.

## Sprint 0 — Estabilização e Alinhamento Técnico

### Objetivo

Remover divergências entre PRD, regras do repositório e estado atual do código.

### Escopo

- [x] Confirmar `core.settings` como settings oficial.
- [x] Configurar SQLite em `data/descontos_bot.db`.
- [x] Garantir WAL e `foreign_keys=ON`.
- [x] Criar `docs/CHECKLIST_PRE_MERGE.md`.
- [x] Atualizar `.gitignore` se necessário para banco, logs, `.env` e sessões.
- [] Mapear o contrato real do `wa_service/`.

### Tarefas do PO

- [x] Validar que o projeto deve manter o nome técnico `core`.
- [x] Confirmar grupo/destino WhatsApp de homologação.
- [x] Criar `.env` local sem versionar.

### Tarefas do Agente IA 1

- [x] Ajustar settings do Django.
- [x] Criar infraestrutura base `apps/_base/models.py`.
- [x] Criar checklist pré-merge.

### Tarefas do Agente IA 2

- [x] Inspecionar `wa_service/src/server.ts` e documentar endpoints.
- [x] Confirmar comando local para iniciar o serviço.
- [x] Validar se `npm test` já passa sem alterar escopo.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
```

- [x] `python3 manage.py check`
- [x] `python3 manage.py makemigrations --dry-run`

Se `wa_service/` foi alterado:

```bash
cd wa_service
npm test
```

- [x] `cd wa_service && npm test`

### Critérios de aceite

- [x] Django usa `data/descontos_bot.db`.
- [x] Não há criação de `db.sqlite3` como banco oficial.
- [x] Checklist pré-merge existe.
- [x] Contrato do WhatsApp está documentado.

## Sprint 1 — Fundação de Domínios e Banco

### Objetivo

Criar a modelagem mínima para marketplace, ofertas, canais, entregas, execuções e configurações.

### Escopo

- [x] `Marketplace`
- [x] `Offer`
- [x] `SocialChannel`
- [x] `Delivery`
- [x] `ScrapingRun`
- [x] `Setting`
- [x] Admin básico em pt-BR.
- [x] Seeds/commands para marketplaces e canal WhatsApp inicial.

### Tarefas do PO

- [x] Validar nomes exibidos no Admin.
- [x] Confirmar canal principal `whatsapp_main`.

### Tarefas do Agente IA 1

- [x] Criar apps e models.
- [x] Aplicar `TimestampedModel`.
- [x] Adicionar `UNIQUE (offer_id, social_channel_id)` em `Delivery`.
- [x] Criar Admin com `verbose_name` em pt-BR.

### Tarefas do Agente IA 2

- [x] Preparar dados iniciais dos marketplaces.
- [x] Documentar variáveis `.env` necessárias para WhatsApp.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
```

- [x] `python3 manage.py check`
- [x] `python3 manage.py makemigrations --dry-run`

### Critérios de aceite

- [x] Todos os models de domínio herdam `TimestampedModel`.
- [x] `Delivery` impede duplicidade por oferta/canal.
- [x] Admin permite visualizar entidades principais.

## Sprint 2 — Scraping e Normalização

### Objetivo

Conectar os scrapers existentes ao domínio Django sem reescrever a lógica que já funciona.

### Escopo

- [x] Adapter comum para `scrapers/mercado_livre.py` e `scrapers/amazon.py`.
- [x] Normalizador de campos.
- [x] Persistência idempotente de ofertas.
- [x] Registro de `ScrapingRun`.
- [x] Detecção básica de CAPTCHA/HTML bloqueado.

### Tarefas do PO

- [x] Rodar scraping local e validar amostra de ofertas.
- [x] Informar se links originais podem ser usados enquanto afiliado não estiver pronto.

### Tarefas do Agente IA 1

- [x] Implementar repository de ofertas.
- [x] Atualizar `first_seen_at` e `last_seen_at`.
- [x] Criar `offer_hash`.

### Tarefas do Agente IA 2

- [x] Adaptar scrapers ao contrato comum.
- [x] Garantir sessão HTTP persistente, headers e delays conservadores.
- [x] Registrar falhas por marketplace sem derrubar o ciclo.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py scrape_marketplace mercadolivre --max-pages 1
python3 manage.py scrape_marketplace amazon --max-pages 1
```

- [x] `python3 manage.py check`
- [x] `python3 manage.py makemigrations --dry-run`
- [x] `python3 manage.py scrape_marketplace mercadolivre --max-pages 1`
- [x] `python3 manage.py scrape_marketplace amazon --max-pages 1`

### Critérios de aceite

- [x] Mercado Livre e Amazon salvam ofertas válidas no SQLite.
- [x] Falha em um marketplace não impede o outro.
- [x] Oferta repetida atualiza registro existente.

## Sprint 3 — Curadoria, Mensagens e Dry Run

### Objetivo

Selecionar as melhores ofertas e gerar mensagens prontas sem envio real.

### Escopo

- [x] Selector com limite de 10 ofertas por marketplace por ciclo, totalizando limite global de 20 ofertas.
- [x] Filtro de ofertas já enviadas.
- [x] Desconto mínimo configurável.
- [x] Message builder em pt-BR.
- [x] Modo `dry_run`.

### Tarefas do PO

- [x] Aprovar o template de mensagem.
- [x] Validar se o tom parece natural para grupos de ofertas.

### Tarefas do Agente IA 1

- [x] Implementar seleção por maior desconto.
- [x] Garantir limite global de 20.
- [x] Integrar `Setting` para limites e desconto mínimo.

### Tarefas do Agente IA 2

- [x] Gerar prévia de mensagens.
- [x] Validar link final: `affiliate_url` ou `product_url`.
- [x] Criar documentação de uso do `dry_run`.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py run_bot --dry-run --once
```

- [x] `python3 manage.py check`
- [x] `python3 manage.py makemigrations --dry-run`
- [x] `python3 manage.py run_bot --dry-run --once`

### Critérios de aceite

- [x] Nenhuma mensagem real é enviada em `dry_run`.
- [x] Prévia mostra no máximo 20 ofertas.
- [x] Ofertas já enviadas não aparecem na seleção.

## Sprint 4 — Integração WhatsApp

Status: fechada. Scheduler local fica fora do escopo desta sprint e será tratado na Sprint 5.

### Objetivo

Enviar mensagens reais via `wa_service/` com controle de falhas e histórico.

### Escopo

- [x] Cliente Django para `wa_service/`.
- [x] Handshake de sessão.
- [x] Envio com intervalo entre mensagens.
- [x] Registro de `Delivery` com status `sent`, `failed` ou `skipped`.
- [x] Bloqueio de distribuição entre 00:00 e 06:00 BRT antes de cada envio.
- [x] Execução real em ciclo único via `python3 manage.py run_bot --once`.

### Tarefas do PO

- [x] Conectar sessão WhatsApp.
- [x] Validar envio para grupo de homologação.
- [x] Autorizar ou bloquear envio real para grupo principal.

### Tarefas do Agente IA 1

- [x] Persistir resultados de entrega.
- [x] Garantir deduplicação por canal.
- [x] Implementar validação de janela de silêncio no domínio de distribuição.

### Tarefas do Agente IA 2

- [x] Ajustar chamadas para o `wa_service/`.
- [x] Documentar start/stop do serviço.
- [x] Validar falhas de sessão desconectada.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py run_bot --dry-run --once
```

- [x] `python3 manage.py check`
- [x] `python3 manage.py makemigrations --dry-run`
- [x] `python3 manage.py run_bot --dry-run --once`

Com autorização do PO:

```bash
python3 manage.py run_bot --once
```

- [x] `python3 manage.py run_bot --once`

### Critérios de aceite

- [x] Envio real funciona em grupo de homologação.
- [x] Falha de WhatsApp não marca oferta como enviada.
- [x] Janela de silêncio bloqueia distribuição.

## Sprint 5 — Scheduler Local e Operação

Status: concluída.

### Objetivo

Rodar o ciclo contínuo local com intervalo randômico e documentação operacional.

### Escopo

- Comando de ciclo único `--once`.
- Comando contínuo.
- Sleep randômico 90-180 minutos.
- Bloqueio 00:00-06:00 BRT.
- Logs operacionais locais.
- README atualizado para o novo produto.

### Tarefas do PO

- Validar rotina local de execução.
- Decidir horário de operação assistida inicial.

### Tarefas do Agente IA 1

- Implementar scheduler local.
- Garantir que timezone BRT seja usado.
- Registrar início/fim de ciclo.

### Tarefas do Agente IA 2

- Atualizar README operacional.
- Criar guia de troubleshooting do WhatsApp.
- Remover referências obsoletas a GitHub Actions/Vercel como fluxo principal.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py run_bot --dry-run --once
```

### Critérios de aceite

- Ciclo único opera fim a fim em `dry_run`.
- Ciclo contínuo calcula intervalo entre 90 e 180 minutos.
- Documentação local substitui o fluxo legado como orientação principal.

## Sprint 6 — Hardening do MVP

### Objetivo

Reduzir risco operacional antes de uso recorrente.

### Escopo

- Blacklist simples de termos.
- Score mínimo por desconto ou economia absoluta.
- Melhorias de logs.
- Checklist operacional antes de envio real.
- Revisão de arquivos sensíveis no git.

### Tarefas do PO

- Definir termos proibidos.
- Validar qualidade das 20 primeiras ofertas selecionadas em `dry_run`.

### Tarefas do Agente IA 1

- Implementar filtros configuráveis.
- Revisar índices e consultas principais.
- Garantir que credenciais não sejam persistidas no banco em texto claro.

### Tarefas do Agente IA 2

- Revisar anti-bot dos scrapers.
- Ajustar delays conservadores.
- Validar que sessões WhatsApp não entram no git.

### DoP

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py run_bot --dry-run --once
```

### Critérios de aceite

- Ofertas ruins óbvias são filtradas.
- Logs permitem auditar coleta, seleção e envio.
- Checklist pré-merge está completo e seguido.

## Backlog Pós-MVP

- Painel customizado baseado em `design_system/refs/design_system.html`.
- Shopee, Netshoes e Centauro.
- Links afiliados por marketplace.
- Histórico de preço.
- Score avançado.
- IA para análise de qualidade e copy.
- Métricas de CTR, conversão e receita.

## Ordem Recomendada Para Dois Agentes

```text
Sprint 0:
  Agente 1 estabiliza Django
  Agente 2 documenta wa_service

Sprint 1:
  Agente 1 cria models/admin
  Agente 2 prepara seeds e docs de ambiente

Sprint 2:
  Agente 1 persiste/normaliza ofertas
  Agente 2 adapta scrapers

Sprint 3:
  Agente 1 implementa selector
  Agente 2 implementa prévia de mensagens

Sprint 4:
  Agente 1 registra Delivery
  Agente 2 integra WhatsApp

Sprint 5:
  Agente 1 implementa scheduler
  Agente 2 atualiza documentação

Sprint 6:
  Agente 1 endurece regras
  Agente 2 endurece scraping/WhatsApp
```
