# Pipeline de Cupons Implementation Plan

> Implementação no worktree isolado `feature/coupons-pipeline`, sem tocar o checkout principal.

**Goal:** Adicionar coleta, validação, curadoria, publicação idempotente e relatório HTML de cupons sem misturá-los ao domínio de ofertas.

**Architecture:** Criar o app Django `apps.coupons` com modelos próprios para candidatos, execução, decisão e entregas. O coletor usa Firecrawl REST com rotação de `FIRECRAWL_API_KEY`/`FIRECRAWL_API_KEYS` e fallback HTTP de baixa confiança. A curadoria recebe contexto sanitizado do Observer e usa o mesmo `HermesRunner`; publicação reutiliza os clientes existentes e o `link_builder` através de um adapter de URL que preserva fonte/campanha/destino afiliado separadamente.

**Tech Stack:** Django 6, SQLite/WAL, `urllib`, Firecrawl REST, Hermes runner, clientes existentes WhatsApp/Telegram, HTML estático.

---

### Task 1: Domínio e coleta normalizada

**Files:**
- Create: `apps/coupons/apps.py`, `apps/coupons/models.py`, `apps/coupons/services/firecrawl_client.py`, `apps/coupons/services/collector.py`
- Modify: `core/settings.py`, `core/settings.py` INSTALLED_APPS
- Create: migration gerada para `coupons`

- [x] Modelar `CouponCandidate`, `CouponRun`, `CouponDecision`, `CouponDelivery` com `TimestampedModel`, hashes idempotentes, URLs separadas, evidências e status.
- [x] Implementar adapter Firecrawl com fallback por credencial e HTTP, sem logar segredos; cada marketplace falha isoladamente.
- [x] Normalizar código/ativação, benefício, mínimos, teto, restrições, validade e evidência sem preencher ausências.

### Task 2: Gates determinísticos e Observer

**Files:**
- Create: `apps/coupons/services/validation.py`, `apps/coupons/services/observer_editorial.py`
- Modify: `apps/curation/services/observer_context.py` apenas se necessário

- [x] Rejeitar vencidos, sem benefício, sem ativação, conflitantes, inválidos, duplicados e sem evidência antes da IA.
- [x] Gerar padrão editorial agregado a partir de `build_observer_context()`, priorizando ordem de benefício/código/CTA/restrições sem copiar texto.
- [x] Validar novamente código, validade, duplicidade e destino imediatamente antes do envio.

### Task 3: Curadoria, posts e afiliados

**Files:**
- Create: `apps/coupons/services/curation.py`, `apps/coupons/services/links.py`, `apps/coupons/services/posts.py`
- Reuse: `apps/curation/services/hermes_runner.py`, `apps/analytics/services/link_builder.py`

- [x] Montar payload próprio de cupons para o mesmo runner Hermes, com schema e decisão/justificativa persistidas.
- [x] Selecionar até cinco por validade/confiabilidade/relevância/benefício/diversidade.
- [x] Escolher destino geral/campanha/storefront quando a fonte fornecer, mantendo URL de validação, campanha e afiliada distintas.
- [x] Gerar WhatsApp e Telegram com benefício, código, restrições e CTA; sem template arbitrário fora do padrão existente.

### Task 4: Publicação, scheduling e relatório

**Files:**
- Create: `apps/coupons/services/publishing.py`, `apps/coupons/services/report.py`, `apps/coupons/management/commands/run_coupon_pipeline.py`, `scripts/coupons-daily.service`, `scripts/coupons-daily.timer`
- Modify: `core/settings.py`, `apps/coupons/apps.py`

- [x] Reutilizar clientes e rate limiters existentes; persistir WhatsApp/Telegram separadamente e não mascarar falhas.
- [x] Tornar execução e entrega idempotentes por `run_key`/`candidate_hash` e constraints por canal.
- [x] Gerar `CENTRAL_BASE_URL/descontos.bot/cupons/YYYY-MM-DD.html` sanitizado e navegável.
- [x] Agendar uma execução diária pelo mecanismo systemd existente, sem criar worker/container novo.

### Task 5: Verificação

- [x] Criar verificador descartável em `/tmp` cobrindo T01–T17 e rodar primeiro em RED contra a API ausente.
- [x] Implementar até GREEN e rodar `python3 manage.py check`, `makemigrations --dry-run`, migração em cópia temporária e execução dry-run.
- [x] Inspecionar diff/status, remover artefatos descartáveis e reportar PASS/FAIL sem simular publicação real.

## Gaps assumidos

- Não existe Firecrawl no código do checkout origin/main; a integração será nova, mantendo fallback explícito por credenciais + HTTP.
- Não será feito envio real, alteração de timers ativos ou push sem autorização operacional adicional; o código e o dry-run serão verificados.
- Conforme `AGENTS.md`, testes não entram como entregável versionado do MVP; os 17 cenários serão executados em verificador descartável.
