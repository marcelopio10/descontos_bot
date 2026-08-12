# Busca Direcionada por Radar Comercial — Plano de Implementação

> Plano para execução em worktree isolado. Não executar diretamente no `main` sujo ou no checkout usado pelo systemd.

**Objetivo:** fazer o observer alterar efetivamente as buscas dos marketplaces, reduzindo a dependência das páginas/categorias genéricas e aumentando a entrada de ofertas novas por marca, categoria, faixa de preço, cupom e oportunidade comercial.

**Arquitetura:** o observer continuará produzindo somente sinais agregados e sanitizados. Uma nova camada de planejamento de buscas transformará esses sinais em consultas concretas por marketplace; os scrapers executarão essas consultas junto de um fallback genérico limitado. Cada oferta carregará a origem da busca para permitir medir se o pool novo realmente mudou. A curadoria IA e o gate de preço histórico continuarão como camadas posteriores, sem baixar artificialmente o critério antes de validar a nova entrada.

**Stack:** Django 6.0.4, Python 3.11+, SQLite em `data/descontos_bot.db`, scrapers existentes, systemd já instalado, Hermes para curadoria IA. Sem Docker, Postgres, FastAPI, mudança de timers ou publicação automática.

---

## Diagnóstico confirmado

A Run `#951` processou 36 candidatas e selecionou 6. O contexto do observer continha sinais úteis — moda, beleza, tecnologia, Nike, Adidas, LG, Samsung, Mizuno, Puma, New Balance e cupons — mas o pool ainda continha principalmente:

- caminhões e brinquedos dinossauro;
- carregadores e acessórios genéricos;
- spinning e esteira;
- whey recorrente;
- ofertas antigas já concentradas no catálogo.

O arquivo `scrapers/category_targets.py` declara `priority_brands` como informativo, consumido pelo score. O arquivo `apps/marketplaces/services/search_radar.py` gera contexto para a IA, mas não gera consultas executadas pelos scrapers. Portanto, a mudança anterior melhorou o ranking/curadoria, mas não alterou a origem do pool.

O plano deve resolver esta lacuna antes de mexer no limiar `history_suspect_price`. Na Run `#951`, 28 de 30 rejeitadas receberam esse sinal; baixar o gate agora apenas aumentaria a publicação de ofertas antigas do mesmo pool.

---

## Resultado esperado

Ao final da implementação e homologação:

- o radar produzirá um plano de consultas executável por marketplace;
- marcas observadas e marcas prioritárias gerarão buscas direcionadas reais;
- categorias e faixas de preço observadas terão queries próprias;
- cupons serão usados como sinal de prioridade, nunca como código publicável;
- o fallback genérico terá orçamento limitado e será identificado;
- cada oferta terá origem de busca auditável;
- será possível comparar pool antigo e pool novo por novidade, família de produto, marca, categoria e marketplace;
- spinning, livros e genéricos continuarão elegíveis, porém não dominarão a coleta;
- Mercado Livre poderá liderar quando houver volume/qualidade/rentabilidade, sem quota artificial;
- o gate de preço histórico só será recalibrado após evidência de que a entrada mudou;
- nenhuma entrega real ocorrerá durante implementação/homologação.

---

## Fora do escopo

- baixar o gate `history_suspect_price` antes da comparação do pool novo;
- transformar `CUPOM` em código publicável;
- autenticar novas APIs de afiliados;
- alterar cadência do `run-bot.service` ou do consumidor WhatsApp;
- blacklisting definitivo de spinning, livros, suplementos ou genéricos;
- substituir a curadoria IA por ranking determinístico;
- Docker, Postgres ou migração de banco;
- publicação em WhatsApp, Telegram, Instagram, Vercel ou GitHub durante homologação.

---

## Governança e segurança

- Criar branch/worktree a partir do `origin/main` atualizado.
- Preservar o checkout operacional e artefatos `site/*.json`, `.hermes/`, banco, logs e `.env` fora do commit.
- Não usar `git add -A`.
- Não carregar `.env` com `source`; usar `dotenv_values()` dentro de subprocessos Python.
- Não armazenar URLs privadas, JIDs, texto bruto do observer, hashes de remetentes ou credenciais no radar.
- Manter SQLite em `data/descontos_bot.db`, WAL e `foreign_keys=ON`.
- Respeitar a janela de silêncio de distribuição; homologação não deve consumir batches.
- Fazer backup branch antes da implementação: `backup/pre-directed-search-radar-20260812`.

---

## Mapa de arquivos e responsabilidades

### Arquivos a criar

- `apps/marketplaces/services/search_query_planner.py`
  - contrato tipado para `SearchQuery` e `SearchPlan`;
  - normalização de marca/categoria/faixa/preço;
  - seleção determinística de consultas por marketplace;
  - orçamento de fallback e prioridade;
  - remoção de termos genéricos e prevenção de duplicatas.

- `apps/marketplaces/services/search_provenance.py`
  - constantes e helpers para origem de coleta;
  - valores permitidos: `radar_brand`, `radar_category`, `radar_price_band`, `radar_coupon_signal`, `priority_catalog`, `generic_fallback`;
  - serialização sanitizada da origem para o payload da oferta.

### Arquivos a modificar

- `apps/marketplaces/services/search_radar.py`
  - manter o contexto sanitizado atual;
  - adicionar `build_search_plan()` que consome sinais agregados e retorna consultas executáveis;
  - separar `observed_count`, `priority_rank`, `query_text`, `marketplace`, `category_code`, `price_band` e `source_kind`;
  - excluir `CUPOM` da query textual e preservá-lo somente em `coupon_signals`.

- `apps/marketplaces/services/radar_mercado.py`
  - reaproveitar dados do radar de marketplace sem transformar sinais em links/códigos publicáveis;
  - não fazer chamada externa nova sem flag existente e sem teste de custo/cadência.

- `scrapers/category_targets.py`
  - manter os targets genéricos existentes como fallback;
  - adicionar configuração declarativa de capacidade de query por marketplace, por exemplo `supports_keyword_query`, `query_url_template`, `max_directed_queries` e `generic_fallback_budget`;
  - separar `priority_brands` informativo do mecanismo que realmente monta query;
  - marcar categorias de baixa prioridade e limite de fallback explícito.

- `scrapers/amazon.py`
  - aceitar lista de `SearchQuery` além das URLs categoriais;
  - executar queries de marca/categoria dentro das páginas de ofertas elegíveis;
  - manter sessão HTTP persistente, headers, delays, retries e CAPTCHA detection;
  - anexar `search_provenance` ao item extraído.

- `scrapers/mercadolivre.py`
  - implementar caminho de busca direcionada compatível com as páginas/rotas atualmente acessíveis;
  - respeitar a limitação conhecida do anti-bot nas URLs `lista.mercadolivre.com.br`;
  - usar somente endpoints/URLs já homologados, com fallback seguro se a query for bloqueada;
  - anexar marketplace e origem da consulta a cada item.

- `scrapers/shopee.py` e/ou scraper de categoria Shopee existente
  - aceitar queries direcionadas quando o contrato atual permitir;
  - manter fallback por categoria;
  - não ligar afiliado ou API nova para implementar este plano.

- `apps/offers/models.py`
  - verificar se já existe campo JSON/metadado de origem de coleta;
  - se já existir, reutilizar;
  - se não existir e a origem não puder ser preservada em JSON existente, criar migração mínima `search_provenance_json` com default vazio, sem guardar texto bruto do observer.

- `apps/curation/services/baseline_snapshot.py`
  - expor contagens de `search_provenance`, novidade, famílias repetidas e fallback genérico;
  - manter `observer_context` sanitizado.

- `apps/curation/management/commands/prepare_ai_curation_batch.py`
  - construir o `SearchPlan` antes da coleta/candidatura;
  - incluir no contexto apenas resumo sanitizado do plano, não URLs privadas nem textos brutos;
  - registrar contagem de queries planejadas, executadas, bloqueadas e fallback;
  - preservar o limite do batch e o fluxo `scraping → Offer → curadoria → CuratedBatch`.

- `apps/curation/services/selector.py`
  - reduzir prioridade do `generic_fallback` e de famílias recorrentes no pool;
  - não excluir uma oferta direcionada apenas por sua origem;
  - não alterar o gate histórico nesta fase.

- `apps/curation/services/quality_score.py`
  - adicionar no máximo um bônus pequeno e auditável para origem direcionada fresca;
  - não usar origem de busca para compensar preço suspeito;
  - manter `history_suspect_price` como sinal separado.

- `apps/curation/services/observer_context.py`
  - expor somente sinais agregados necessários ao planejador;
  - garantir que marcas, categorias, faixas e cupons continuem sanitizados.

- `apps/curation/tests/` e `apps/marketplaces/tests/`
  - usar os módulos de teste existentes para regressões focadas, sem criar uma suíte paralela como entregável;
  - cobrir contrato do planejador, sanitização, fallback e integração com o candidato.

- `docs/CHECKLIST_PRE_MERGE.md`
  - acrescentar verificação de origem de busca, cobertura direcionada, orçamento de fallback e ausência de dados privados no JSON.

---

## Plano de execução

### Fase 0 — Baseline e backup

- [x] Atualizar `origin/main` e registrar divergência da branch.
- [x] Criar `backup/pre-directed-search-radar-20260812` no HEAD atual.
- [x] Criar worktree `.worktrees/directed-search-radar` a partir do `origin/main`.
- [ ] Ler `AGENTS.md`, checklist pré-merge e runbook de produção.
- [ ] Registrar o baseline da Run `#951`:
  - 36 candidatas;
  - 6 selecionadas;
  - categorias e marketplaces;
  - 28/30 rejeições com `history_suspect_price`;
  - famílias repetidas;
  - proporção de `generic_fallback` desconhecida a ser medida após instrumentação.
- [x] Não alterar checkout operacional nem consumir batches.

### Fase 1 — Contrato de consulta e proveniência

- [x] Escrever teste para `SearchQuery` com marketplace, query, categoria, faixa, prioridade e origem.
- [x] Escrever teste que rejeita query vazia, `CUPOM` isolado, JID, URL privada e texto bruto.
- [x] Implementar `search_query_planner.py` com tipos imutáveis e normalização.
- [ ] Definir orçamento padrão por ciclo:
  - 60% queries de marca/categoria observadas;
  - 20% marcas do catálogo prioritário ainda não cobertas;
  - 10% faixa de preço/categoria;
  - 10% fallback genérico;
  - redistribuir slots de uma classe sem candidatos válidos, sem forçar query fraca.
- [ ] Tornar o orçamento configurável por marketplace em `CATEGORY_TARGETS`.
- [x] Executar somente os testes focados do planner.

### Fase 2 — Transformar radar em plano executável

- [x] Adicionar `build_search_plan()` ao `search_radar.py`.
- [ ] Selecionar marcas observadas com frequência mínima e marcas prioritárias não cobertas.
- [ ] Gerar queries concretas, por exemplo:
  - `nike tênis desconto`;
  - `adidas camiseta promoção`;
  - `lattafa perfume`;
  - `growth whey`;
  - `dark lab creatina`;
  - `insider camiseta`;
  - `samsung fone`;
  - `tramontina cozinha`.
- [x] Gerar queries de categoria/faixa quando não houver marca suficiente.
- [x] Usar cupons apenas como sinal de prioridade; nunca concatenar `CUPOM` como código.
- [x] Deduplicar consultas por marketplace, família, slug e janela de ciclo.
- [ ] Registrar consultas planejadas e motivo da seleção em estrutura sanitizada.
- [ ] Validar que o plano da Run real teria queries diferentes das páginas genéricas atuais.

### Fase 3 — Integração com scrapers

- [ ] Identificar o ponto de entrada comum usado pelo `run_bot` para cada scraper.
- [x] Fazer Amazon executar consultas direcionadas dentro do limite de páginas e delays existentes.
- [x] Fazer Mercado Livre usar apenas rotas de busca permitidas/homologadas; registrar falha de query como `query_blocked`, não como sucesso genérico.
- [x] Fazer Shopee executar queries direcionadas quando suportado; preservar fallback por categoria.
- [x] Propagar `search_provenance` do resultado do scraper até `Offer`.
- [x] Marcar ofertas coletadas sem origem direcionada como `generic_fallback`.
- [x] Aplicar orçamento para que fallback não ocupe todo o ciclo.
- [x] Testar cada scraper com fixtures locais, sem depender de rede em teste unitário.
- [ ] Executar uma coleta controlada em homologação e medir queries planejadas versus executadas.

### Fase 4 — Integração com seleção e curadoria

- [x] Incluir resumo de proveniência no `serialize_offer_for_ai()`.
- [ ] Expor para a IA:
  - origem da query;
  - marca/categoria/faixa associada;
  - frescor da coleta;
  - se veio de fallback.
- [x] Não enviar textos brutos do observer ou cupons como códigos.
- [ ] Aplicar penalidade de prioridade ao fallback genérico quando existir alternativa direcionada equivalente.
- [ ] Preservar cooldown, deduplicação, baixa prioridade de spinning/livros/genéricos e liderança natural do Mercado Livre.
- [ ] Manter `history_suspect_price` sem redução durante o primeiro ciclo.
- [ ] Adicionar logs e campos de auditoria para diferenciar:
  - oferta não encontrada;
  - oferta encontrada via query direcionada;
  - oferta encontrada via fallback;
  - oferta rejeitada por preço;
  - oferta rejeitada por qualidade editorial.

### Fase 5 — Observabilidade do pool novo

- [x] Expandir `baseline_snapshot` com:
  - `query_source_counts`;
  - `directed_query_count`;
  - `generic_fallback_count`;
  - `new_family_count`;
  - `repeated_family_rate`;
  - `brand_coverage`;
  - `category_coverage`;
  - `marketplace_distribution`;
  - `history_suspect_price_rate`.
- [ ] Gerar JSON sanitizado de comparação entre baseline e novo pool.
- [ ] Validar que o relatório separa “sinal observado”, “query planejada”, “query executada”, “oferta encontrada” e “oferta enviada”.
- [ ] Não considerar aumento de candidatas como sucesso se a taxa de famílias repetidas permanecer igual.

### Fase 6 — Homologação controlada

- [x] Rodar `prepare_ai_curation_batch --mode homolog --runner mock` contra banco temporário migrado.
- [ ] Rodar uma homologação com dados reais de coleta, sem envio, usando limite externo controlado.
- [ ] Comparar com Run `#951` e com o último lote homologado:
  - distribuição por marketplace;
  - categorias;
  - marcas;
  - origem da busca;
  - famílias novas;
  - repetição;
  - taxa de `history_suspect_price`;
  - selecionadas por qualidade;
  - presença de spinning/whey/genéricos.
- [ ] Gate de aprovação do pool novo:
  - pelo menos 50% das candidatas com origem direcionada;
  - fallback genérico abaixo de 25%, salvo marketplace sem suporte;
  - queda de pelo menos 30% na taxa de famílias recorrentes do baseline;
  - presença de pelo menos 3 famílias/marcas fora do padrão antigo;
  - nenhum aumento de risco de privacidade;
  - nenhum envio real.
- [ ] Se o pool continuar dominado pelas famílias antigas, bloquear promoção e investigar o scraper específico; não baixar o gate de preço.

### Fase 7 — Recalibração posterior do gate comercial

- [ ] Somente após duas homologações com pool direcionado, medir a taxa de `history_suspect_price` por origem de busca.
- [ ] Separar:
  - preço suspeito com histórico suficiente;
  - preço suspeito apenas por heurística antiga;
  - oferta nova sem histórico suficiente;
  - oferta antiga com histórico confiável.
- [ ] Testar em shadow uma eventual redução de penalidade, nunca remover o gate diretamente.
- [ ] Comparar qualidade, cliques e entregas antes de promover qualquer ajuste.

### Fase 8 — Release e produção

- [ ] Rodar `manage.py check` no worktree e no checkout operacional.
- [ ] Rodar `makemigrations --check --dry-run`.
- [ ] Rodar testes focados existentes.
- [ ] Rodar script ad hoc `tempfile.NamedTemporaryFile(prefix='hermes-verify-', suffix='.py', dir='/tmp', delete=False)` e removê-lo em `finally`.
- [x] Validar JSONs contra URLs privadas, JIDs, texto bruto, hashes e segredos.

### Estado de execução em 2026-08-12

- Implementado no worktree `.worktrees/directed-search-radar`, sem promoção.
- Testes focados finais: `23 passed`.
- `manage.py check`: passou.
- `makemigrations --check --dry-run`: passou.
- Homologação sintética/controlada: 12 candidatas, 12 selecionadas, 25% fallback, nenhum envio real.
- Plano sintético de 6 queries: 5 direcionadas (marca, catálogo prioritário, categoria e faixa) e nenhum fallback genérico.
- JSONs de homologação não continham `raw_text`, JID, `sender_hash`, `external_message_id` ou segredos.
- Bloqueio: a homologação com coleta real não foi executada porque o worktree isolado não possui as tabelas do observer e não é permitido apontá-lo ao banco operacional. A promoção permanece bloqueada até um ciclo real controlado contra uma cópia segura do SQLite.
- Falhas amplas preexistentes/configuracionais observadas: 1 teste de reentrada do selector e 2 testes do radar de mercado; os arquivos correspondentes não foram alterados por este plano.
- [ ] Rebase sobre `origin/main` atualizado.
- [ ] Push controlado e fast-forward de `main` somente com gate de homologação aprovado.
- [ ] Preservar artefatos gerados do checkout operacional em stash nomeado.
- [ ] Reiniciar o produtor somente após sincronização do checkout.
- [ ] Fazer smoke production bounded apenas se houver candidatas aprovadas:
  - candidato-limit externo pequeno;
  - batch `production/ready` fresco;
  - inspeção persistida antes do consumo;
  - consumer limitado ao mesmo máximo;
  - verificação de `CuratedBatch` e `Delivery` após envio.
- [ ] Se a IA rejeitar tudo, registrar falha editorial e não forçar oferta.

---

## Critérios de aceite

1. Uma execução real de homologação registra queries direcionadas planejadas e executadas.
2. Pelo menos metade do pool possui origem `radar_brand`, `radar_category`, `radar_price_band` ou `priority_catalog`.
3. O fallback genérico é mensurável e não domina a coleta.
4. O pool apresenta famílias novas em relação à Run `#951`.
5. A busca contém marcas observadas e prioritárias de forma efetiva, não apenas no prompt da IA.
6. O contexto da IA permanece sanitizado.
7. O gate de preço histórico continua auditável e não é usado para compensar pool ruim.
8. Spinning, livros e genéricos não dominam o pool, mas permanecem elegíveis conforme regras de baixa prioridade.
9. Mercado Livre pode liderar sem balanceamento artificial.
10. Homologação não gera entrega externa.
11. Produção só é promovida após validação persistida e reversível.

---

## Riscos e mitigação

- **Marketplace não suporta query direta:** registrar `query_blocked`, preservar fallback limitado e medir cobertura separadamente.
- **Anti-bot do Mercado Livre:** não inventar endpoint; usar somente rotas conhecidas e tratar bloqueio como ausência de execução.
- **Queries direcionadas reduzem volume:** redistribuir para categoria/faixa e manter fallback pequeno, sem reabrir todo o pool genérico.
- **Marcas observadas refletem grupos copiadores:** exigir combinação marca + categoria + desconto/frescor e manter curadoria IA.
- **Preço histórico insuficiente em ofertas novas:** manter estado `insufficient_history`, não classificar automaticamente como suspeito.
- **Pool direcionado ainda contaminado:** bloquear promoção e rastrear proveniência por oferta até o scraper.
- **Mudança de schema:** preferir JSON existente; se migração for indispensável, testar em cópia SQLite e aplicar `makemigrations --check`.
- **Execução durante silêncio:** não consumir batches antes do horário permitido e verificar `expires_at`.

---

## Verificação do plano

- Cobertura: o plano trata a falha confirmada entre radar e scraper.
- Segurança: não reduz gates nem publica código de cupom.
- Governança: preserva SQLite, WSL, checkout sujo e produção controlada.
- Medição: separa query planejada, executada, oferta encontrada e oferta enviada.
- Reversibilidade: implementação isolada, fallback preservado e promoção posterior.
- Sem placeholders: não há `TBD`, `TODO` ou tarefa sem critério de execução.
