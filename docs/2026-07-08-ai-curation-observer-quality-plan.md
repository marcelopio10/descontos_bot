# Plano de Implementação — Observer + Qualidade da Curadoria IA

> **Para execução futura no Hermes:** após aprovação, usar `subagent-driven-development` e executar em blocos pequenos, com worktree isolado por sprint, validação focada e commit atômico por bloco.

**Objetivo:** fazer os dados agregados do observer influenciarem de fato a curadoria IA e melhorar a qualidade do pool de ofertas antes de chegar ao agente.

**Arquitetura:** manter o selector/score determinístico como baseline e fallback. O observer deve entrar como contexto agregado e sanitizado no payload da IA, nunca como cópia/URL/sender/grupo de concorrentes. A melhoria principal é em dois pontos: contexto real para o agente e pool de candidatos balanceado por marketplace + qualidade editorial.

**Stack:** Django, SQLite local/prod conforme ambiente, management commands, modelos `apps.curation`, `apps.market_intel`, `apps.offers`, testes com `.venv/bin/python -m pytest` e `manage.py check`.

---

## 0. Diagnóstico que originou o plano

Data da análise: 2026-07-08.

Achados principais:

1. O observer coleta dados úteis, mas hoje quase não influencia a curadoria real.
   - `apps/curation/services/observer_context.py::build_observer_context()` existe.
   - Nenhum fluxo real chama esse serviço antes de preparar o lote IA.
   - `prepare_ai_curation_batch.py` injeta apenas um contexto operacional dummy:
     - `source`
     - `skip_images`
     - `real_send_enabled`
   - Últimos `CurationRun.observer_context_json` confirmaram ausência de tendências reais.

2. A percepção de ofertas fracas parece vir mais do funil scraper → candidatos → ranking do que do observer.
   - Há volume fresco razoável de ofertas.
   - O pool de candidatos ainda nasce muito influenciado por `discount_pct` e preço.
   - Muitos candidatos balanceados entram com `quality_score` abaixo de 55.

3. O target 40/30/30 por marketplace existe, mas a entrega real ainda fica enviesada para Mercado Livre.
   - WhatsApp 7d: ML 325, Amazon 137, Shopee 52.
   - Telegram 7d: ML 134, Amazon 26, Shopee 5.

4. Scrapers precisam ser auditados por qualidade, não só por volume.
   - Shopee coleta, mas parte do catálogo é barato/genérico.
   - Amazon tem falhas intermitentes de coleta.
   - Mercado Livre domina volume, mas também gera itens medianos/fracos.

---

## 1. Escopo aprovado para implementação

### Dentro do escopo

- Conectar contexto real do observer ao payload da IA.
- Garantir sanitização forte do contexto enviado ao agente.
- Melhorar montagem do pool de candidatos antes da IA.
- Adicionar métricas de qualidade do pool e diagnóstico operacional.
- Auditar scrapers por qualidade, novidade e aderência editorial.
- Adicionar testes focados para cada mudança.

### Fora do escopo neste plano

- Copiar ofertas, textos, URLs ou links dos grupos concorrentes.
- Usar dados sensíveis de grupo, sender, JID, URLs ou raw text no prompt.
- Substituir a decisão da IA por ranking determinístico final.
- Reescrever todos os scrapers.
- Alterar templates finais de mensagem, exceto se necessário para expor sinais de curadoria já existentes.

---

## 2. Princípios de implementação

1. Compliance primeiro.
   - Observer só como sinal agregado.
   - Nada de raw copy, URLs, sender, JID, hash determinístico de copy ou identificação de grupo no prompt/público.

2. IA continua curadora.
   - Código prepara bons candidatos e aplica safety gates.
   - IA decide `selected_for_batch=true`.
   - `optimize_curation_batch()` continua normalizando posições/distribuição, não escolhendo ofertas no lugar da IA.

3. Qualidade antes de volume.
   - Volume de scraper sem qualidade editorial não resolve o problema.
   - Pool ruim gera curadoria ruim mesmo com modelo bom.

4. Mudanças incrementais.
   - Um bloco por vez.
   - Teste antes/depois.
   - Commit atômico após validação.

---

## 3. Bloco A — Ligar observer real ao payload da IA

**Objetivo:** substituir o contexto dummy por um contexto real, agregado e sanitizado.

### Arquivos

- Modificar: `apps/curation/management/commands/prepare_ai_curation_batch.py`
- Modificar/testar: `apps/curation/tests/test_prepare_ai_curation_batch_command.py`
- Usar existente: `apps/curation/services/observer_context.py`
- Possivelmente ajustar: `apps/curation/tests/test_observer_context.py`

### Tarefas

#### A1. Adicionar teste que prova uso do observer context

Criar/ajustar teste em `apps/curation/tests/test_prepare_ai_curation_batch_command.py`:

- Arrange:
  - criar `ObservedWhatsAppGroup` e `ObservedWhatsAppMessage` recente;
  - criar ofertas/canal necessários para `prepare_ai_curation_batch`;
  - mockar runner real ou usar `FakeHermesRunner` conforme padrão existente;
- Act:
  - chamar `prepare_ai_curation_batch` via `call_command`;
- Assert:
  - `CurationRun.observer_context_json` contém:
    - `messages_analyzed` > 0;
    - `marketplace_counts`;
    - `editorial_label_counts`;
  - não contém chaves sensíveis (`text`, `urls`, `group_jid`, `sender_hash`, `external_message_id`).

Comando esperado inicialmente:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_prepare_ai_curation_batch_command.py -v --tb=short
```

Resultado esperado antes da implementação: falha porque o contexto ainda é dummy.

#### A2. Implementar chamada a `build_observer_context()`

Em `prepare_ai_curation_batch.py`:

- importar `build_observer_context`;
- trocar:

```python
observer_context = {
    'source': 'prepare_ai_curation_batch_command',
    'skip_images': bool(options['skip_images']),
    'real_send_enabled': False,
}
```

por estrutura combinada:

```python
observer_context = build_observer_context(lookback_hours=24)
observer_context.update({
    'source': 'prepare_ai_curation_batch_command',
    'skip_images': bool(options['skip_images']),
    'real_send_enabled': False,
})
```

Observação: se `build_observer_context()` lançar erro de sanitização, a preparação deve falhar explicitamente. Não esconder vazamento de privacidade.

#### A3. Ajustar prompt para explicar como usar observer

Em `apps/curation/services/hermes_runner.py::build_curation_prompt()`:

Adicionar instrução curta:

- usar `observer_context` como tendência agregada;
- não copiar concorrentes;
- favorecer categorias/mecânicas recorrentes quando houver candidatas seguras equivalentes;
- não selecionar item ruim só porque apareceu como tendência.

Teste em `apps/curation/tests/test_hermes_runner.py`:

- assert de frases-chave no prompt:
  - `observer_context`
  - `sinais agregados`
  - `não copie URLs/copy`
  - `não selecione oferta fraca apenas por tendência`

#### A4. Verificação do bloco A

Rodar:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_observer_context.py apps/curation/tests/test_prepare_ai_curation_batch_command.py apps/curation/tests/test_hermes_runner.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py check
```

Validação manual segura:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --dry-run --runner mock --skip-images
```

Depois inspecionar o último `CurationRun` e confirmar que `observer_context_json` tem tendências agregadas e não tem dados sensíveis.

---

## 4. Bloco B — Melhorar o pool de candidatos antes da IA

**Objetivo:** manter balanceamento por marketplace, mas selecionar os melhores candidatos por qualidade editorial antes de enviar ao agente.

### Arquivos

- Modificar: `apps/curation/management/commands/prepare_ai_curation_batch.py`
- Possível criar: `apps/curation/services/candidate_pool.py`
- Testar: `apps/curation/tests/test_prepare_ai_curation_batch_command.py`

### Design recomendado

Extrair a lógica de `_balanced_marketplace_candidates()` para um serviço testável, por exemplo:

`apps/curation/services/candidate_pool.py`

Funções sugeridas:

```python
def build_balanced_quality_candidate_pool(queryset, *, limit: int, config: SelectionConfig) -> list[Offer]:
    ...
```

Critérios:

1. Calcular `quality_score_breakdown(offer)`.
2. Separar candidatos fortes (`score >= config.min_quality_score`) e fracos.
3. Dentro de cada marketplace, ordenar por:
   - score desc;
   - desconto desc;
   - preço atual desc ou critério já existente;
   - título/id para estabilidade.
4. Preencher cotas por `DEFAULT_TARGET_DISTRIBUTION` usando primeiro candidatos fortes.
5. Se faltar oferta forte em algum marketplace, preencher com:
   - forte de outro marketplace;
   - só então fraco como fallback explícito.
6. Não filtrar safety/blacklist aqui se já estiver em `_eligible_offers()`, para evitar duplicação.

### Tarefas

#### B1. Teste: pool deve priorizar score acima de desconto bruto

Criar cenário com:

- oferta ML com desconto altíssimo e score baixo;
- oferta ML com desconto menor e score alto;
- verificar que a de score alto vem antes.

#### B2. Teste: Shopee segura não deve sumir quando existe

Criar cenário com muitas ML/Amazon de desconto alto e poucas Shopee boas.

Assert:

- pool final inclui Shopee quando há Shopee com `score >= min_quality_score`;
- respeita aproximadamente 40/30/30 quando há disponibilidade.

#### B3. Teste: fallback fraco só entra se faltar forte

Criar cenário com poucos candidatos fortes para preencher `limit`.

Assert:

- candidatos fracos aparecem somente depois dos fortes;
- teste registra comportamento esperado sem bloquear o lote inteiro.

#### B4. Implementar serviço e trocar command

- Criar `candidate_pool.py` se o arquivo deixar o command mais limpo.
- `prepare_ai_curation_batch.Command._get_candidates()` passa a usar o novo serviço.
- Manter função antiga como wrapper ou remover se os testes forem atualizados.

#### B5. Verificação do bloco B

Rodar:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_prepare_ai_curation_batch_command.py apps/curation/tests/test_baseline_snapshot.py apps/curation/tests/test_batch_optimizer.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py check
```

Validação manual:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --dry-run --runner mock --skip-images
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py inspect_ai_curation_batch --channel whatsapp_main --compare-selector
```

Critérios de aceite:

- Menos candidatos com `baseline.score < 55` no input da IA.
- Shopee aparece no input quando há Shopee forte disponível.
- Amazon não some quando há Amazon forte disponível.
- Nenhuma regressão no schema da IA.

---

## 5. Bloco C — Diagnóstico de qualidade dos scrapers

**Objetivo:** medir qualidade/novidade/aderência editorial por marketplace para decidir ajustes nos scrapers com evidência.

### Arquivos

- Criar: `apps/scraping/management/commands/audit_scraper_quality.py`
- Testar: `apps/scraping/tests/test_audit_scraper_quality.py`
- Usar dados existentes: `Offer`, `ScrapingRun`, `quality_score_breakdown`, categorias e raw payload.

### Saída do comando

O comando deve imprimir JSON ou tabela simples com:

- marketplace;
- ofertas frescas;
- score médio;
- score p50/p75/p90 se simples de implementar;
- quantidade abaixo de 55;
- top categorias;
- ticket médio;
- % com marca forte indireta via score/popularity se disponível;
- quantidade de duplicatas aproximadas por `normalized_title` ou `offer_hash` recente;
- quantidade por `raw_payload.source_label` / `category_hint` quando existir.

Exemplo:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py audit_scraper_quality --lookback-hours 36 --format json
```

### Tarefas

#### C1. Criar teste do comando com dados mínimos

- Criar ofertas de 2 marketplaces.
- Rodar command via `call_command`.
- Assert que JSON contém os campos principais.

#### C2. Implementar comando sem side effects

- Somente leitura.
- Não alterar ofertas, scraping runs, JSON público ou entregas.
- Não imprimir URLs ou dados sensíveis.

#### C3. Adicionar flags úteis

- `--lookback-hours`, default 36.
- `--marketplace`, opcional.
- `--format json|text`, default text.
- `--min-score`, default config atual.

#### C4. Verificação do bloco C

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/scraping/tests/test_audit_scraper_quality.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py check
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py audit_scraper_quality --lookback-hours 36 --format text
```

Critérios de aceite:

- Comando roda sem modificar banco.
- Ajuda a identificar marketplace/categoria com muito volume e baixa qualidade.
- Não expõe URLs/copy sensível.

---

## 6. Bloco D — Ajustes guiados nos scrapers

**Objetivo:** corrigir pontos fracos encontrados pelo diagnóstico, sem reescrever tudo.

Este bloco só deve começar depois de rodar o comando do Bloco C em dados reais.

### D1. Amazon — estabilidade de coleta

Achado atual:

- Amazon teve falhas intermitentes `0 ofertas válidas`.
- Também já houve erro histórico `Python int too large to convert to SQLite INTEGER`.

Arquivos prováveis:

- `scrapers/amazon.py`
- `apps/offers/services/normalizer.py`
- `apps/scraping/services/runner.py`
- testes em `apps/scraping/tests/test_amazon_scraping.py` e/ou `apps/offers/tests/test_normalizer.py`

Tarefas:

1. Reproduzir falha com comando real/dry-run, sem alterar dados produtivos quando possível.
2. Garantir cap de `review_count` malformado no normalizer se ainda não estiver coberto.
3. Adicionar teste para review count gigante/malformado.
4. Melhorar logging de `0 ofertas válidas` com causa provável:
   - bloqueio HTML;
   - seletor vazio;
   - normalização descartando tudo;
   - erro de parsing.

Verificação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/offers/tests/test_normalizer.py apps/scraping/tests/test_amazon_scraping.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py scrape_marketplace amazon --max-pages 1
```

### D2. Shopee — qualidade e novidade

Achado atual:

- Shopee coleta volume, mas muita oferta é barata/genérica.
- Já existe histórico de problema com paginação/novidade e variação de preço.

Arquivos prováveis:

- `scrapers/shopee.py`
- `apps/marketplaces/services/shopee_normalizer.py`
- `apps/marketplaces/tests/test_shopee_scraper_category.py`
- `apps/marketplaces/tests/test_shopee_normalizer.py`

Tarefas:

1. Medir novidade real por ciclo:
   - quantos hashes já existiam;
   - quantos novos;
   - por categoria/página.
2. Confirmar se página 2+ está ativa e testada.
3. Penalizar ou filtrar itens com sinais de baixa qualidade editorial:
   - preço extremamente baixo sem marca/categoria clara;
   - acessórios genéricos repetitivos;
   - títulos com ruído forte.
4. Não remover a proteção de variação de preço; manter filtro inteligente.

Verificação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/marketplaces/tests/test_shopee_normalizer.py apps/marketplaces/tests/test_shopee_scraper_category.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py collect_shopee_offers --categories --dry-run
```

### D3. Mercado Livre — reduzir dominância de itens medianos

Achado atual:

- ML domina elegibilidade e entregas.
- Muitos itens entram por desconto alto, mas com score baixo.

Arquivos prováveis:

- `scrapers/mercado_livre.py`
- `scrapers/category_targets.py`
- `apps/curation/services/quality_filters.py`
- `apps/curation/services/category_weights.py`

Tarefas:

1. Identificar categorias/source labels com maior quantidade de score < 55.
2. Ajustar targets de busca, não só blacklist.
3. Adicionar soft penalties para classes recorrentes de baixa conversão se necessário.
4. Evitar bloquear categorias inteiras quando houver bons itens nelas.

Verificação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/ apps/scraping/tests/ -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py audit_scraper_quality --marketplace mercadolivre --lookback-hours 36
```

---

## 7. Bloco E — Métrica de gap concorrência vs catálogo próprio

**Objetivo:** transformar o observer em diagnóstico acionável para coleta e curadoria.

### Arquivos

- Criar/Modificar: `apps/curation/services/observer_context.py`
- Possível criar: `apps/market_intel/services/gap_analysis.py`
- Testar: `apps/curation/tests/test_observer_context.py` ou novo `apps/market_intel/tests/test_gap_analysis.py`

### Ideia

Adicionar ao contexto agregado um bloco seguro como:

```json
{
  "catalog_gap_signals": {
    "observer_marketplace_counts": {...},
    "own_fresh_marketplace_counts": {...},
    "observer_editorial_labels": {...},
    "own_candidate_quality": {...},
    "notes": [
      "observer aponta cupom/pix/parcelamento; pool atual tem baixa presença desses sinais"
    ]
  }
}
```

Nada de raw text, URLs ou grupo.

### Tarefas

1. Criar teste de gap com dados artificiais.
2. Implementar agregador simples.
3. Incluir no `build_observer_context()`.
4. Instruir prompt da IA a usar `catalog_gap_signals` como desempate e alerta, não como regra absoluta.

Verificação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_observer_context.py apps/curation/tests/test_hermes_runner.py -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --dry-run --runner mock --skip-images
```

Critérios de aceite:

- Contexto mostra lacunas agregadas úteis.
- Sanitização continua passando.
- Payload da IA permanece dentro do schema esperado.

---

## 8. Bloco F — Observabilidade operacional da curadoria

**Objetivo:** facilitar auditoria futura sem precisar scripts temporários.

### Arquivos

- Modificar: `apps/curation/management/commands/inspect_ai_curation_batch.py`
- Possível criar: `apps/curation/management/commands/audit_ai_curation_inputs.py`
- Testar: `apps/curation/tests/test_prepare_ai_curation_batch_command.py` ou novo teste de comando.

### Funcionalidades

Adicionar comando/flag que mostre para últimos N runs:

- quantidade de candidatos;
- distribuição do input por marketplace;
- distribuição final;
- score médio por marketplace;
- quantidade abaixo de min score;
- se `observer_context` real estava presente;
- motivo de falha do Hermes, se houver.

Exemplo:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py audit_ai_curation_inputs --runs 10
```

Critérios de aceite:

- Ajuda a responder rapidamente: problema foi observer, scraper, pool ou IA?
- Não expõe URLs/raw copy.
- Não altera dados.

---

## 9. Sequência recomendada de execução

### Sprint 1 — Observer no prompt

- Bloco A completo.
- Commit sugerido:

```bash
git add apps/curation/management/commands/prepare_ai_curation_batch.py apps/curation/services/hermes_runner.py apps/curation/tests/
git commit -m "feat: include observer context in ai curation"
```

### Sprint 2 — Pool de candidatos por qualidade

- Bloco B completo.
- Commit sugerido:

```bash
git add apps/curation/management/commands/prepare_ai_curation_batch.py apps/curation/services/ apps/curation/tests/
git commit -m "feat: rank ai curation candidates by quality"
```

### Sprint 3 — Auditoria de scraper quality

- Bloco C completo.
- Rodar em dados reais e anexar resumo no PR/relatório.
- Commit sugerido:

```bash
git add apps/scraping/management/commands/audit_scraper_quality.py apps/scraping/tests/
git commit -m "feat: add scraper quality audit command"
```

### Sprint 4 — Ajustes guiados por evidência

- Executar D1/D2/D3 conforme diagnóstico do Sprint 3.
- Commits separados por marketplace.

### Sprint 5 — Gap analysis e observabilidade

- Blocos E e F.
- Commit(s) separados se crescer demais.

---

## 10. Checklist de validação final

Antes de considerar a implementação aprovada:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py check
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/ apps/market_intel/tests/ apps/scraping/tests/ apps/marketplaces/tests/ -v --tb=short
```

Validação manual mínima:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --dry-run --runner mock --skip-images
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py inspect_ai_curation_batch --channel whatsapp_main --compare-selector
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py audit_scraper_quality --lookback-hours 36 --format text
```

Se usar runner real em homologação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_principal --mode homolog --runner real --profile descontos-bot --skip-images
```

Validar no banco:

- último `CurationRun.observer_context_json` contém tendências reais;
- não contém dados sensíveis;
- `baseline_summary_json.marketplace_counts` e `actual_distribution_json` estão coerentes;
- quantidade de candidatos fracos no input caiu;
- Shopee/Amazon aparecem quando há candidatos fortes disponíveis;
- falhas do Hermes não são mascaradas como “sem lote pronto”.

---

## 11. Riscos e mitigação

### Risco: vazamento de dados dos grupos observados

Mitigação:

- manter `assert_sanitized_context()` como gate obrigatório;
- adicionar testes com strings contendo URL/JID/raw text;
- falhar fechado se houver dado sensível.

### Risco: código voltar a selecionar deterministicamente no lugar da IA

Mitigação:

- pool só escolhe candidatos, não lote final;
- `optimize_curation_batch()` continua aceitando apenas `selected_for_batch=true` da IA;
- testes garantem que o batch final depende da decisão do runner.

### Risco: filtrar demais e zerar marketplace

Mitigação:

- fallback explícito para candidatos fracos só quando faltarem fortes;
- relatório do pool mostra `weak_count`;
- manter target como direção, não obrigação cega.

### Risco: scraper parecer saudável por volume, mas ruim por qualidade

Mitigação:

- comando `audit_scraper_quality` vira parte da rotina;
- medir score, categoria, ticket, novidade e duplicidade.

### Risco: generated/public JSON sujar commits

Mitigação:

- antes de cada bloco, checar `git status`;
- não commitar `site/offers.json`, `site/links.json`, `site/market-intel.json` salvo quando o objetivo for publicação;
- usar worktree isolado por sprint.

---

## 12. Estado esperado depois da implementação

Ao final dos blocos principais:

- O agente passa a receber contexto real dos grupos, mas somente agregado/sanitizado.
- O pool de candidatos melhora antes da IA, reduzindo ofertas fracas por desconto bruto.
- A distribuição por marketplace fica mais próxima do alvo quando há oferta forte disponível.
- Scrapers passam a ser avaliados por qualidade e novidade, não só volume.
- Fica mais fácil diagnosticar se uma leva ruim veio de coleta, ranking, prompt, falha Hermes ou falta de candidatos bons.

---

## 13. Próximo passo após aprovação

Após aprovação deste plano:

1. Criar worktree isolado baseado em `origin/develop`.
2. Executar Sprint 1 com TDD.
3. Validar localmente.
4. Commit atômico.
5. Integrar em `develop` seguindo o fluxo já usado no projeto.
6. Só depois avançar para Sprint 2.
