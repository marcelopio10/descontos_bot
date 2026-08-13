# Arquitetura de Busca Comercial Real — Plano de Refatoração

> Execução obrigatoriamente em worktree isolado. Não alterar produção até a homologação do produtor e do curador passarem separadamente.

**Objetivo:** substituir o fluxo atual de coleta genérica por uma arquitetura observável de descoberta comercial, capaz de buscar ofertas concretas por oportunidade, marketplace, marca, categoria, faixa de preço e frescor, sem cair silenciosamente para o catálogo antigo.

**Diagnóstico confirmado:** o produtor executa ciclos reais, mas o pool recente contém `unknown`/`generic_fallback`, enquanto o adapter engole exceções do planner. Amazon teve ciclo com zero ofertas válidas. A curadoria atual seleciona ofertas persistidas e não prova que a nova busca foi executada. Firecrawl CLI existe, mas está sem autenticação.

**Princípio:** nenhum erro de descoberta pode virar coleta genérica silenciosa. Cada consulta terá estado `planned`, `executed`, `blocked`, `failed` ou `empty`; cada oferta terá proveniência obrigatória; a curadoria só considerará “pool novo” quando a origem estiver comprovada.

## Escopo

### Incluído

- refatoração do contrato entre radar, planner, scrapers e ingestão;
- observabilidade de queries e ofertas por ciclo;
- busca comercial por intenção, não apenas por palavra de marca;
- agentes especializados somente como camada de seleção de oportunidades e pesquisa pública, não como substitutos cegos dos scrapers;
- Firecrawl como fonte complementar autorizada para páginas públicas, com rate limit e sem contornar CAPTCHA/login;
- validação comercial de preço, desconto, estoque, seller, reviews, comissão quando disponível e frescor;
- bloqueio de fallback silencioso;
- homologação real contra cópia segura do SQLite;
- rollback e promoção controlada.

### Fora do escopo inicial

- scraping autenticado ou bypass de anti-bot;
- login em marketplaces via Firecrawl;
- alterar cadência de WhatsApp;
- baixar `history_suspect_price` antes de medir o pool novo;
- publicação automática em Instagram;
- adicionar credenciais Firecrawl ou marketplace sem autorização/configuração externa;
- trocar SQLite, Django ou systemd.

## Arquitetura proposta

### Camada 1 — Opportunity Planner

Entrada: observer agregado, catálogo de marcas/categorias, estoque de oportunidades cobertas e performance histórica.

Saída: `SearchOpportunity` com:

- `opportunity_id` determinístico;
- marketplace-alvo;
- intenção: `brand_product`, `category_product`, `price_value`, `coupon_signal`, `newness`, `commercial_gap`;
- termos concretos de produto, não somente `oferta`;
- faixa de preço;
- requisito mínimo de desconto;
- prioridade;
- expiração;
- motivo sanitizado.

O planner não criará queries genéricas como `growth oferta` ou `moda`; exigirá um núcleo de produto, por exemplo `growth whey`, `nike tenis`, `lattafa perfume`, `tramontina panela`, `samsung fone`.

### Camada 2 — Source Adapters

Cada adapter implementará o mesmo contrato:

- `plan(opportunity) -> list[SourceQuery]`;
- `execute(query) -> SourceResult`;
- `normalize(result) -> list[CommercialCandidate]`;
- `health() -> SourceHealth`.

Estados obrigatórios:

- `planned`;
- `executed`;
- `blocked`;
- `failed`;
- `empty`;
- `partial`.

O adapter nunca chama fallback genérico automaticamente após falha direcionada. O fallback, se autorizado pelo orçamento, será uma query separada e explicitamente registrada.

### Camada 3 — Commercial Validator

Valida cada candidata antes de persistir:

- título contém o produto esperado ou marca/intenção compatível;
- preço atual positivo;
- preço original não é aceito apenas porque foi derivado de desconto artificial;
- desconto histórico separado de desconto declarado;
- disponibilidade e URL válidas;
- seller/loja identificável quando a fonte fornece;
- reviews e vendas preservados como sinais, não como garantia;
- variações de preço marcadas;
- duplicidade por produto canônico e URL;
- risco comercial e editorial separados.

### Camada 4 — Curation Pool

Só entram no pool principal candidatas com proveniência válida. Ofertas antigas sem proveniência ficam em `legacy_pool` e não podem ser apresentadas como resultado da nova busca.

A IA recebe:

- intenção da oportunidade;
- origem e estado da query;
- sinais comerciais;
- frescor;
- histórico de preço;
- flags editoriais;
- risco.

A IA não recebe texto bruto do observer nem credenciais.

## Agentes especializados

Agentes não serão usados para “raspar tudo”. Serão especializados por tarefa:

1. `commercial-opportunity-agent`
   - transforma sinais agregados em oportunidades concretas;
   - não acessa banco de produção diretamente;
   - saída JSON validada.

2. `marketplace-search-agent`
   - escolhe queries permitidas por marketplace;
   - não publica nem envia mensagens;
   - não contorna bloqueios;
   - pode usar Firecrawl apenas em fontes públicas autorizadas.

3. `offer-validation-agent`
   - compara título, preço, desconto, seller, reviews, estoque e frescor;
   - devolve evidências e rejeições estruturadas;
   - não aprova uma oferta sem dados mínimos.

4. `commercial-curator-agent`
   - escolhe o lote final entre candidatas validadas;
   - mantém a decisão editorial;
   - não reabilita candidata reprovada por preço ou segurança.

A primeira implementação deve manter o caminho determinístico funcionando; os agentes entram atrás de feature flags e em modo shadow antes de influenciar produção.

## Firecrawl

Firecrawl será tratado como fonte complementar, não como bypass:

- autenticação/configuração somente se houver credencial autorizada;
- páginas públicas e fontes permitidas;
- limite de requisições por ciclo;
- cache por URL/query;
- timeout e circuito de falha;
- URL, título, preço e evidência armazenados de forma sanitizada;
- se Firecrawl estiver indisponível, registrar `source_unavailable`; não mascarar com fallback genérico.

O CLI local está instalado, porém atualmente sem autenticação. Até configurar uma conta autorizada, Firecrawl permanece em adapter desabilitado/shadow.

## Arquivos e módulos

### Criar

- `apps/marketplaces/services/commercial_opportunity.py`
  - `SearchOpportunity`, `OpportunityPlan`, normalização e deduplicação.

- `apps/marketplaces/services/source_contracts.py`
  - `SourceQuery`, `SourceResult`, `SourceHealth`, estados e contratos.

- `apps/marketplaces/services/query_execution.py`
  - execução por ciclo, timeout, estados, métricas e circuit breaker.

- `apps/marketplaces/services/commercial_validator.py`
  - validação de candidata comercial.

- `apps/marketplaces/services/source_provenance.py`
  - proveniência obrigatória, sanitização e classificação legacy/directed/fallback.

- `apps/marketplaces/services/firecrawl_source.py`
  - adapter público opcional, desabilitado por padrão sem configuração autorizada.

- `apps/marketplaces/tests/test_commercial_opportunity.py`
- `apps/marketplaces/tests/test_source_contracts.py`
- `apps/marketplaces/tests/test_query_execution.py`
- `apps/marketplaces/tests/test_commercial_validator.py`
- `apps/marketplaces/tests/test_firecrawl_source.py`

### Modificar

- `apps/scraping/services/adapters.py`
  - remover `except Exception: return ()`;
  - delegar ao executor de queries;
  - impedir fallback silencioso;
  - registrar resultado por consulta.

- `scrapers/amazon.py`
  - separar busca direcionada, categoria legada, bloqueio e vazio;
  - registrar URL/query e motivo de zero resultados;
  - corrigir seletor ou marcar fonte indisponível, sem declarar sucesso.

- `scrapers/mercado_livre.py`
  - validar se rota de busca retorna resultados de intenção;
  - reconhecer bloqueio HTML/anti-bot;
  - não tratar lista vazia como coleta bem-sucedida.

- `scrapers/shopee.py`
  - usar keyword + categoria apenas quando o contrato API permitir;
  - propagar query e estado da resposta;
  - separar ranking de comissão de relevância comercial.

- `apps/scraping/services/runner.py`
  - persistir resumo de queries executadas, falhas, vazios e candidatas.

- `apps/offers/services/normalizer.py` e `repository.py`
  - preservar proveniência nova quando a oferta já existir;
  - mesclar metadados de origem sem apagar evidência anterior;
  - distinguir `legacy_replayed` de `directed_fresh`.

- `apps/curation/services/baseline_snapshot.py`
  - excluir legacy sem proveniência do relatório de “pool novo”;
  - expor taxas de directed, fallback, unknown, failed, empty e novas famílias.

- `apps/curation/management/commands/prepare_ai_curation_batch.py`
  - consumir resultado real do produtor;
  - bloquear apresentação como nova busca quando `unknown` dominar;
  - registrar oportunidade/query/candidata.

- `apps/orchestration/management/commands/run_bot.py`
  - separar captura, curadoria e entrega;
  - não criar lote comercial quando o produtor falhar ou o pool novo não atingir o gate.

## Plano de execução TDD

### Fase 0 — Baseline e instrumentação read-only

- [x] Criar worktree a partir do `origin/main` atual.
- [x] Registrar ciclos recentes por marketplace, status, `total_collected`, `total_valid`, erros e duração.
- [x] Medir `unknown`, `generic_fallback`, `directed` e famílias repetidas.
- [x] Executar o planner atual diretamente e capturar exceções reais, sem engoli-las.
- [x] Verificar se o `run_bot` chama scraping antes da curadoria em cada ciclo.
- [x] Não alterar produção.

### Fase 1 — Contratos e oportunidades comerciais

- [x] Escrever testes que rejeitam query sem produto, `ofertas`, `desconto` ou `CUPOM` isolados.
- [x] Implementar `CommercialOpportunity` com intenção, produto, marca, categoria, faixa e prioridade.
- [x] Criar catálogo prioritário para marcas/produtos comerciais.
- [x] Garantir que cada oportunidade gere pelo menos uma query concreta ou seja marcada `unplannable`.

### Fase 2 — Executor observável

- [x] Escrever testes para `executed`, `blocked`, `failed` e `empty`.
- [x] Remover fallback silencioso quando a busca direcionada está habilitada.
- [ ] Persistir resumo de execução em `ScrapingRun.raw_summary` se campo existente; se não houver, usar JSON de auditoria sem migração até validar necessidade.
- [ ] Adicionar logs sanitizados por marketplace/query hash.
- [ ] Testar timeout, exceção do planner e resposta vazia.

### Fase 3 — Refatorar adapters de marketplace

- [x] Amazon: validar query relevante, cards e proveniência.
- [x] Mercado Livre: detectar redirecionamento para verificação de tráfego.
- [x] Shopee: detectar erro GraphQL e interromper o ciclo direcionado.
- [x] Propagar proveniência até `Offer.raw_payload`.
- [x] Preservar metadados ao atualizar uma oferta existente.
- [x] Bloquear `unknown` no pool novo.

### Fase 4 — Validator comercial

- [x] Rejeitar produto incompatível com a oportunidade.
- [ ] Separar desconto declarado, desconto calculado e histórico.
- [ ] Aceitar oferta nova sem histórico como `insufficient_history`, não como `history_suspect_price` automático.
- [ ] Rejeitar faixa de preço insegura, seller ausente quando obrigatório e URL inválida.
- [ ] Manter risco editorial separado do score comercial.

### Fase 5 — Agentes e Firecrawl em shadow

- [ ] Criar schemas JSON para os quatro agentes.
- [ ] Implementar `commercial-opportunity-agent` em modo mock/shadow.
- [ ] Implementar `offer-validation-agent` em modo shadow contra fixtures.
- [x] Criar adapter Firecrawl desabilitado sem credencial.
- [x] Executar Firecrawl somente como contrato shadow; CLI local confirmado sem autenticação.
- [ ] Se credencial autorizada estiver disponível, executar somente pesquisa pública limitada e registrar resultados sem publicar.
- [ ] Comparar agentes com planner determinístico; não promover divergência automaticamente.

### Fase 6 — Homologação real

- [ ] Copiar o SQLite com `backup`/modo somente leitura.
- [x] Executar os adapters reais contra cópia segura do SQLite, com limite de queries e sem consumer.
- [x] Verificar queries planejadas/executadas e estados.
- [x] Verificar proveniência por candidata no payload.
- [ ] Executar curadoria mock sobre o pool produzido.
- [ ] Gerar relatório comparando Run #951 e o novo ciclo.
- [ ] Gate mínimo:
  - pelo menos 60% directed/priority_catalog;
  - `unknown` abaixo de 5%;
  - fallback abaixo de 20%;
  - pelo menos 5 famílias novas;
  - Amazon não pode declarar sucesso com zero ofertas;
  - nenhum bloqueio mascarado;
  - nenhuma entrega externa.

**Resultado da primeira homologação real (2026-08-12):** Amazon executou 6 queries e retornou 88 candidatas após validação; Mercado Livre foi bloqueado por `account-verification`/tráfego suspeito; Shopee foi bloqueada por erro GraphQL `10010`. O gate multi-marketplace está reprovado. A branch permanece isolada e não foi promovida.

### Fase 7 — Produção controlada

- [ ] Commit em branch isolada.
- [ ] Rebase sobre `origin/main` atual.
- [ ] Rodar checks e testes no checkout operacional após sync.
- [ ] Ativar apenas o executor determinístico; agentes permanecem shadow.
- [ ] Reiniciar produtor.
- [ ] Observar um ciclo completo e verificar persistência.
- [ ] Só preparar smoke production se o pool cumprir o gate.
- [ ] Não consumir lote se a proveniência estiver `unknown` ou se Amazon/qualquer fonte estiver falhando sem estado explícito.

## Critérios de conclusão

O trabalho só pode ser declarado concluído quando:

1. um ciclo real mostra queries concretas planejadas e executadas;
2. o pool novo possui proveniência válida na maioria das ofertas;
3. as famílias antigas deixam de dominar;
4. falhas de fonte são visíveis e não viram fallback silencioso;
5. Amazon, Mercado Livre e Shopee têm estados de saúde separados;
6. validator comercial separa histórico insuficiente de preço suspeito;
7. agentes/Firecrawl não são necessários para mascarar falhas dos adapters;
8. homologação persistida não envia mensagens;
9. promoção é reversível e validada no checkout do systemd.

## Bloqueios conhecidos

- Firecrawl está sem autenticação nesta máquina.
- Não usar credencial inventada nem pedir login automático.
- O banco operacional só pode ser copiado para homologação; nunca apontar worktree de implementação diretamente para ele.
- A mudança atual foi promovida, mas deve ser considerada experimental até cumprir este plano.
