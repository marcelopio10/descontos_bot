# Plano: inteligência de mercado incremental e migração para Postgres/Docker

## Objetivo

Criar uma camada própria de inteligência de mercado para o `descontos.bot`, capaz de aprender com:

- sinais observados nos grupos;
- ofertas próprias encontradas e enviadas;
- decisões de curadoria;
- deliveries confirmados;
- cliques, conversões e comissões somente quando houver fonte oficial;
- desempenho por marketplace, categoria, marca, preço, desconto e recência.

A camada deverá reduzir a dependência estratégica dos grupos monitorados sem depender de processamento diário. O observer continuará recebendo mensagens continuamente; o processamento operacional deverá ser incremental e o relatório analítico continuará diário.

A migração de SQLite para Postgres será feita como uma fase de robustez da infraestrutura, não como pré-requisito para validar a lógica do aprendizado. A lógica deverá ser homologada primeiro com shadow/dry-run.

## Contexto atual e fatos confirmados

- Projeto: `/mnt/c/Users/marce/Documents/Projetos/descontos.bot`.
- Django usa SQLite em `core/settings.py`.
- Não foi localizado Docker Compose ou configuração Docker existente no projeto.
- O adapter Evolution recebe mensagens continuamente via webhook e persiste o buffer do observer.
- `WA_OBSERVER_LOOKBACK_HOURS=24`.
- `market-intel.timer` roda uma consolidação diária às 22h BRT.
- `apps/curation/services/observer_context.py` já gera contexto agregado e sanitizado.
- O contexto já chega a `CurationRun` e é usado como sinal opcional pelo `quality_score`.
- O contexto atual é orientado a contagens/radar; ainda não existe um funil persistente de oportunidade observada até delivery.
- O profile `descontos-bot` deve executar e produzir diagnósticos/recomendações, mas não decidir sozinho política de produção, deploy, publicação ou mudança destrutiva.
- O Quebra-Galho/default continuará governando promoção de políticas e decisões de produção.

## Princípios e limites

1. **Tempo real operacional, consolidação diária analítica**
   - O webhook e o buffer continuam contínuos.
   - Candidatas e sinais de frescor devem ser processados em micro-lotes de 10–15 minutos.
   - Snapshots de aprendizado podem ser recalculados a cada hora.
   - Relatórios históricos permanecem diários.

2. **Aprendizado não é publicação automática**
   - Uma tendência observada pode orientar busca, mas não autoriza envio.
   - Toda oferta ainda precisa de validação de preço, disponibilidade, qualidade, afiliado, imagem e curadoria.

3. **Sem memória textual indiscriminada**
   - A memória da inteligência de mercado será persistida em banco como dados agregados, features, eventos e snapshots versionados.
   - Não armazenar texto bruto de terceiros, JIDs, hashes de remetente, URLs de grupos ou credenciais em artefatos públicos.

4. **Conversão e comissão só com fonte oficial**
   - Delivery confirmado não é conversão.
   - Clique, conversão e comissão devem manter origem, período e nível de certeza.

5. **Mudança gradual e reversível**
   - Primeiro shadow/dry-run.
   - Depois experimento controlado.
   - Só então promoção explícita para produção.

## Arquitetura proposta

### 1. Camada de ingestão contínua

Manter o fluxo atual:

```text
Evolution webhook
→ evolution_adapter
→ observer buffer persistido
→ collect incremental
→ parser/ingestion Django
```

Adicionar cursor/idempotência para que cada mensagem seja processada uma vez por etapa, sem depender apenas de uma janela de 24 horas.

### 2. Camada de oportunidades observadas

Criar uma entidade interna agregada, sem exposição de dados brutos:

- `ObservedOpportunity` ou equivalente;
- fingerprint determinístico por marketplace/produto/link canônico/título normalizado;
- primeira e última ocorrência;
- contagem de ocorrências;
- marketplaces, categorias, marcas e faixas de preço;
- recência e expiração;
- status do funil;
- origem agregada dos grupos, sem JID público;
- relação opcional com `Offer` própria;
- versão do parser e da política que gerou o registro.

Estados sugeridos:

```text
observed
normalized
matched_catalog
candidate
enrichment_pending
enriched
sent_to_curation
expired
rejected_for_freshness
```

A entidade não deverá copiar captions ou mensagens inteiras.

### 3. Camada de enriquecimento e candidatas

A cada 10–15 minutos:

- consumir novas mensagens normalizadas;
- deduplicar oportunidades;
- classificar marketplace/categoria/marca/faixa de preço;
- procurar correspondência em `Offer`;
- quando não houver correspondência, gerar sinal para busca/enriquecimento;
- aplicar política de frescor;
- nunca publicar diretamente a partir do observer.

SLA inicial:

```text
0–15 min: prioridade alta
15 min–2 h: prioridade normal com revalidação
>2 h: somente inteligência histórica, salvo recorrência nova
```

### 4. Camada de memória e aprendizado

Criar snapshots versionados, por exemplo:

- `MarketLearningSnapshot`;
- `SearchPolicySnapshot`;
- `LearningEvent`;
- `ObservedOpportunity`;
- `OutcomeAttribution` ou equivalente.

Cada snapshot deverá conter:

- período analisado;
- versão do schema;
- versão da política;
- amostra e cobertura;
- tendências por marketplace/categoria/marca/preço/desconto;
- recorrência e decaimento temporal;
- lacunas de catálogo;
- taxa de match;
- taxa de aprovação;
- taxa de seleção;
- delivery confirmado;
- cliques/conversões/comissões oficiais, quando disponíveis;
- recomendações com confiança e justificativa agregada;
- estado `shadow`, `candidate`, `approved`, `active`, `rolled_back`.

O profile `descontos-bot` consumirá o snapshot vigente e produzirá eventos/recomendações sanitizados para o default.

### 5. Camada de políticas de busca

Gerar recomendações, não comandos irreversíveis:

- aumentar consultas por categoria/marketplace;
- criar consultas categoria + marca + faixa de preço;
- priorizar marketplaces com gaps observados;
- detectar marcas/categorias emergentes;
- reduzir buscas com baixo match ou baixa qualidade;
- priorizar sinais frescos e recorrentes;
- calibrar limites por faixa de preço/desconto.

Cada recomendação deverá ter:

- evidência agregada;
- período;
- tamanho da amostra;
- confiança;
- impacto esperado;
- risco;
- validade/expiração;
- estratégia de rollback.

### 6. Funil de atribuição

Instrumentar explicitamente:

```text
observed_messages
→ observed_unique_opportunities
→ catalog_matches
→ search_candidates
→ enriched_offers
→ curation_decisions
→ selected_batch_items
→ sent_deliveries
→ official_clicks
→ official_conversions
→ official_commission
```

A dashboard deverá distinguir cobertura por mensagens de cobertura por oferta única, evitando repetir o problema atual de 45% de cobertura em mensagens versus 5,7% de sobreposição em ofertas únicas.

## Migração SQLite → Postgres

### Fase A — preparar compatibilidade

1. Centralizar a configuração de banco em variáveis de ambiente, sem credenciais versionadas.
2. Introduzir `DATABASE_URL` ou variáveis equivalentes para SQLite/Postgres.
3. Garantir que testes possam continuar usando SQLite temporariamente.
4. Corrigir incompatibilidades específicas de SQLite/Postgres:
   - concorrência e locks;
   - JSONField e índices;
   - timestamps/timezone;
   - constraints e upserts;
   - tipos numéricos;
   - consultas agregadas;
   - comandos de manutenção.
5. Adicionar health check de banco e teste de conexão.

### Fase B — containerização local

Criar, sem publicar automaticamente:

- `Dockerfile` do Django/worker;
- `docker-compose.yml` ou `compose.yaml` para Postgres e aplicação;
- volume persistente do Postgres;
- healthcheck do banco;
- rede interna;
- `.env.example` sem segredos;
- scripts de bootstrap/migrate/backup/restore;
- política de retenção e diretório de backups ignorado pelo Git.

O Evolution adapter poderá permanecer como serviço separado na primeira etapa. A containerização deve começar pelo banco e pelo processo Django/worker, reduzindo o raio de mudança.

### Fase C — homologação com cópia do SQLite

1. Criar backup imutável do SQLite.
2. Subir Postgres isolado em homologação.
3. Migrar esquema com `manage.py migrate`.
4. Exportar/importar dados com validação de contagens e checksums agregados.
5. Comparar relatórios SQLite versus Postgres:
   - contagem de ofertas;
   - mensagens observadas;
   - grupos;
   - decisões;
   - deliveries;
   - relatórios diários;
   - snapshots de aprendizado.
6. Executar testes focados e smoke real sem envio de produção.

### Fase D — dual-read ou cutover controlado

Preferência: cutover controlado, sem dual-write prolongado no início.

1. Congelar escrita por janela curta planejada.
2. Fazer dump final do SQLite.
3. Importar delta no Postgres.
4. Validar contagens e últimas entidades.
5. Iniciar aplicação apontando para Postgres.
6. Manter SQLite intacto como rollback somente leitura.
7. Monitorar locks, latência, filas, erros e integridade.
8. Reverter para SQLite se qualquer gate crítico falhar.

Não remover o SQLite nem apagar volumes antes de um período de estabilidade definido e de backup restaurável comprovado.

## Backup / rollback

Antes de qualquer alteração destrutiva ou migração:

1. Criar branch de checkpoint:

```text
a backup/pre-market-intelligence-postgres-20260808
```

2. Criar cópia física protegida de:

- banco SQLite;
- `core/settings.py`;
- arquivos de ambiente, sem expor conteúdo;
- modelos e migrations relevantes;
- units/timers existentes;
- scripts de coleta e publicação.

3. Usar `.backup/` ignorado pelo Git.
4. Testar restauração do dump antes do cutover.
5. Manter procedimento de rollback documentado:
   - parar workers;
   - apontar `DATABASE_URL` para SQLite/instância anterior;
   - restaurar configuração;
   - validar health, migrations e contagens;
   - reabrir processamento.

## Fases de implementação

### Fase 0 — baseline e contratos

- Congelar métricas atuais.
- Adicionar dashboard do funil com denominadores explícitos.
- Definir schema de eventos e snapshots.
- Definir SLA de frescor.
- Definir política de privacidade e retenção.
- Confirmar quais fontes oficiais existem para clique/conversão/comissão por marketplace.

**Gate:** baseline reproduzível e contratos aprovados.

### Fase 1 — ingestão incremental

Arquivos prováveis:

- `apps/market_intel/models.py`;
- nova migration de `apps.market_intel`;
- `apps/market_intel/services/ingestion.py`;
- `apps/market_intel/services/parser.py`;
- novo comando `collect_incremental_market_intel`;
- novo worker/timer de 10–15 minutos;
- `apps/market_intel/tests/`.

**Gate:** idempotência, cursor, frescor e ausência de vazamento.

### Fase 2 — oportunidades e funil

Arquivos prováveis:

- novos modelos em `apps/market_intel/models.py` ou app dedicado `apps/learning`;
- serviço de matching/deduplicação;
- integração com `apps/offers`;
- integração somente de sinal com `apps/curation`;
- testes de match por URL/produto/título/fingerprint.

**Gate:** nenhum envio novo; somente shadow/dry-run e métricas do funil.

### Fase 3 — snapshots e recomendações

Arquivos prováveis:

- `apps/market_intel/services/learning.py`;
- `apps/market_intel/services/search_policy.py`;
- comando `build_market_learning_snapshot`;
- persistência de versões e eventos;
- publicação sanitizada na Central Hermes;
- integração com `observer_context.py`.

**Gate:** recomendações reproduzíveis, amostra suficiente, confiança e rollback.

### Fase 4 — shadow/dry-run de 24–72 horas

- Processar candidatas em cadência incremental.
- Comparar contra o ciclo diário atual.
- Medir latência e frescor.
- Medir match, aprovação, seleção e delivery.
- Não alterar distribuição de produção automaticamente.

**Gate:** demonstrar ganho de timing sem aumento de falsos positivos, duplicidade ou ofertas expiradas.

### Fase 5 — Postgres e Docker em homologação

- Executar backup/checkpoint.
- Criar container Postgres.
- Migrar esquema/dados.
- Executar suite focada e smoke.
- Comparar relatórios e snapshots.

**Gate:** dados reconciliados e rollback testado.

### Fase 6 — experimento controlado de política

- Selecionar uma pequena fração ou canal controlado.
- Promover somente uma política de busca por vez.
- Registrar versão antes/depois.
- Comparar baseline de qualidade, frescor, aprovação, envio e resultados oficiais.

**Gate:** Quebra-Galho autoriza ou rejeita promoção.

### Fase 7 — cutover de produção

- Janela operacional explícita.
- Sem smoke de envio fora da janela permitida.
- Cutover para Postgres somente após reconciliação final.
- Monitoramento reforçado.
- Atualizar timers, runbooks, Central Hermes e Obsidian.

**Gate:** health, filas, curation runs, deliveries e relatórios estáveis.

## Arquivos prováveis a alterar

Projeto:

- `core/settings.py`;
- `requirements.txt` ou equivalente de dependências;
- `apps/market_intel/models.py`;
- migrations novas de `apps.market_intel` ou novo app;
- `apps/market_intel/services/ingestion.py`;
- `apps/market_intel/services/observer_context.py` ou integração com `apps/curation/services/observer_context.py`;
- `apps/curation/services/quality_score.py`;
- `apps/curation/management/commands/prepare_ai_curation_batch.py`;
- novos comandos de aprendizado e snapshots;
- testes em `apps/market_intel/tests/`, `apps/curation/tests/` e integração.

Infraestrutura:

- `Dockerfile`;
- `compose.yaml`;
- `.dockerignore`;
- `.env.example`;
- scripts de migrate/backup/restore;
- units/timers systemd ou equivalente de worker;
- documentação de operação.

Central Hermes/profile:

- relatório sanitizado de aprendizado em `/home/marce/central-hermes/descontos-bot/`;
- script de publicação do snapshot;
- eventos sanitizados no profile `descontos-bot`;
- runbook de governança e rollback.

## Testes e validação

### Testes unitários

- fingerprint e deduplicação;
- matching observado → oferta;
- expiração por frescor;
- agregação de tendências;
- cálculo de confiança;
- geração de políticas;
- sanitização recursiva;
- idempotência do cursor;
- compatibilidade SQLite/Postgres.

### Testes de integração

- webhook → buffer → ingestão incremental;
- ingestão → oportunidade;
- oportunidade → match/enriquecimento;
- snapshot → `observer_context`;
- snapshot → curadoria dry-run;
- Postgres com migrations reais;
- backup/restore;
- container healthcheck e restart.

### Gates operacionais

- `manage.py check`;
- migrations limpas;
- testes focados;
- testes de integração contra Postgres real;
- relatório sanitizado válido;
- nenhum JID, URL privada, texto bruto, token ou segredo em artefatos públicos;
- latência p95 da coleta incremental dentro do SLA;
- zero duplicação de oportunidade por reprocessamento;
- nenhuma publicação de produção durante shadow/dry-run;
- delivery só contabilizado como confirmado quando `delivery_status=sent`;
- rollback restaurado em ambiente de homologação.

## Riscos e trade-offs

### Postgres agora versus depois

- **Agora:** melhora concorrência, observabilidade, JSON/índices e base para aprendizado; aumenta complexidade operacional.
- **Depois:** permite validar a lógica no SQLite primeiro; mantém risco de fazer duas migrações e pode limitar testes de concorrência.

Recomendação: implementar contratos e funil primeiro, mas preparar a compatibilidade imediatamente; executar Postgres em homologação antes de ativar aprendizado operacional.

### Micro-lote versus evento por mensagem

- **Evento por mensagem:** menor latência, maior complexidade e custo operacional.
- **Micro-lote de 10–15 min:** bom equilíbrio para ofertas de curta duração.
- **Diário:** simples, mas inadequado para timing comercial.

Recomendação: micro-lote incremental inicialmente; evento por mensagem somente se os dados demonstrarem necessidade.

### Aprendizado automático versus políticas aprovadas

- **Automático:** velocidade, mas risco de feedback ruim e drift.
- **Aprovado por snapshot:** mais governável e reversível.

Recomendação: aprendizado automático para recomendações; promoção de política sob governança do Quebra-Galho.

### Banco único versus dual-write

- **Dual-write:** reduz risco teórico de cutover, mas aumenta inconsistência e complexidade.
- **Cutover com backup/delta:** mais simples e auditável.

Recomendação: cutover controlado com backup restaurável e janela curta, evitando dual-write prolongado.

## Perguntas em aberto antes da execução

1. O Postgres será local em Docker, em outro host, ou em serviço gerenciado?
2. Qual volume de retenção de mensagens e snapshots é necessário?
3. O primeiro worker incremental será systemd, Docker Compose ou ambos?
4. Qual SLA mínimo de observação → candidatura é desejado: 15, 30 ou 60 minutos?
5. Quais fontes oficiais de clique/conversão/comissão estarão disponíveis na primeira versão?
6. Qual percentual do tráfego poderá entrar no experimento controlado depois do shadow?
7. O adapter Evolution continuará fora do Compose na primeira migração?

## Critério de conclusão

O plano estará concluído quando:

- o observer processar sinais incrementalmente sem depender do relatório diário;
- o funil completo tiver estados e métricas persistidos;
- snapshots de inteligência forem versionados, sanitizados e consumidos pelo profile;
- políticas de busca forem geradas com evidência e rollback;
- shadow/dry-run demonstrar melhora de timing;
- Postgres rodar em homologação com dados reconciliados;
- backup e restauração forem comprovados;
- o cutover de produção for explicitamente autorizado pelo Quebra-Galho;
- Central Hermes, runbooks e Obsidian refletirem a arquitetura final.
