# Plano de Melhoria Comercial, Busca e Recorrência do descontos.bot

> **Para agentes executores:** executar este plano em worktree/branch isolado, usando a skill de execução de planos e validando cada gate antes de avançar.

**Objetivo:** reduzir repetição de ofertas, melhorar a diversidade comercial e transformar sinais do observer em buscas direcionadas por marca, categoria, faixa de preço e marketplace, sem publicar ou enviar em produção durante a implementação.

**Arquitetura:** preservar o fluxo atual `scraping → Offer → selector/curadoria IA → CuratedBatch → consumer WhatsApp`. A primeira etapa será determinística e reversível: recorrência, cooldown, prioridade editorial e radar de busca. O observer continuará fornecendo somente sinais agregados e sanitizados. A IA continuará como curadora; as regras determinísticas não substituirão sua decisão, apenas controlarão elegibilidade, qualidade e repetição.

**Stack:** Django, SQLite em `data/descontos_bot.db`, scrapers existentes, `market_intel`, curadoria IA Hermes, systemd apenas para operação já existente. Sem Docker, Postgres, deploy, publicação ou envio real neste plano.

---

## Escopo e resultado esperado

Ao final da implementação em homologação, o sistema deverá:

- penalizar ofertas e famílias de produtos enviadas recentemente;
- permitir reentrada somente com cooldown vencido ou melhoria comercial material;
- classificar spinning, livros e itens genéricos como baixa prioridade, sem blacklist automática total;
- alimentar o radar com oportunidades de marcas, categorias, faixas de preço e marketplaces observados;
- ampliar buscas para um conjunto comercial de marcas, incluindo Insider, perfumes árabes e suplementos;
- permitir que o Mercado Livre lidere o pool e os envios quando sua oferta, volume e rentabilidade justificarem; garantir apenas cobertura mínima dos demais marketplaces quando houver candidatos bons e elegíveis;
- gerar um lote de homologação novo e compará-lo a um lote baseline;
- demonstrar queda de repetição e aumento de diversidade antes de qualquer promoção.

Fora do escopo desta fase:

- publicação no GitHub/Vercel;
- envio para WhatsApp ou Telegram;
- mudança dos timers de produção;
- alteração de regras de comissão ou links de afiliado;
- uso de `CUPOM` como código publicável;
- blacklisting definitivo de livros, spinning ou suplementos;
- migração para Postgres/Docker;
- promessa de conversão sem dados oficiais de vendas/comissões.

---

## Estado inicial e restrições operacionais

Antes de editar:

1. Usar como checkout operacional o diretório configurado pelo serviço: `/mnt/c/Users/marce/Documents/Projetos/descontos.bot`.
2. Ler `AGENTS.md`, o plano ativo de curadoria e os runbooks de produção.
3. Registrar `git status`, branch, worktrees, divergência com `origin/main` e arquivos gerados sujos.
4. Não trabalhar diretamente em `main` sujo/divergente.
5. Criar branch/worktree isolado a partir do `origin/main` atualizado.
6. Preservar `site/offers.json`, `site/links.json`, `site/market-intel.json`, banco, `.env` e artefatos runtime fora do commit.
7. Não consumir o lote `production/ready` existente sem inspeção e autorização específica de envio.

---

## Catálogo inicial de marcas e sinais de busca

O catálogo deve ser configurado como prioridade editorial/search hint, não como garantia de que qualquer item da marca será publicado.

### Moda, calçados e lifestyle

- Insider
- Nike
- Adidas
- Puma
- Mizuno
- Asics
- New Balance
- Olympikus
- Fila
- Havaianas
- Colcci
- Reserva
- Lupo
- Centauro
- Netshoes
- Under Armour
- Oakley
- Levi's
- Calvin Klein
- Tommy Hilfiger
- Lacoste
- Vans
- Converse

### Perfumes e beleza

Marcas de perfumes árabes conhecidas e variantes de busca:

- Lattafa
- Afnan
- Armaf
- Rasasi
- Al Haramain
- Maison Alhambra
- Swiss Arabian
- Khadlaj
- Fragrance World
- Paris Corner
- Asdaaf
- Riiffs
- Ajmal
- Al Wataniah
- Emir
- Ard Al Zaafaran

Também manter radar para marcas de beleza e cuidados já observadas, como Natura, Eudora, Avon, O Boticário, Lola, Elseve, L'Oréal, Kérastase, Taiff, Oral-B e Colgate.

### Suplementos e nutrição esportiva

- Growth Supplements
- Max Titanium
- Dark Lab
- Integralmedica
- Vitafor
- DUX Nutrition
- Adaptogen
- Soldiers Nutrition
- Atlhetica Nutrition
- Bodyaction
- Probiótica
- Essential Nutrition
- Nutrify
- Optimum Nutrition
- Universal Nutrition
- MuscleTech
- Black Skull
- New Millen
- Sanavita
- Equaliv

As buscas devem cobrir, quando disponíveis, whey, creatina, pré-treino, barras/proteínas, vitaminas e acessórios de treino. Suplementos devem permanecer sujeitos a filtros de segurança, autenticidade, preço, marketplace e qualidade editorial.

### Casa, tecnologia e marcas de alta intenção

- Samsung
- LG
- Xiaomi
- Motorola
- JBL
- Sony
- Logitech
- Acer
- Lenovo
- Apple
- Electrolux
- Brastemp
- Consul
- Mondial
- Oster
- Arno
- Tramontina
- Philips Walita
- WAP
- Kärcher

O catálogo deve ser versionado em estrutura declarativa, permitindo atualizar marcas sem espalhar strings pelo código.

---

# Fases de implementação

## Fase 0 — Baseline, proteção e instrumentação

**Objetivo:** criar comparação confiável antes de mudar seleção ou buscas.

**Arquivos prováveis:**

- Criar: `docs/superpowers/plans/` ou documentação operacional equivalente, somente se necessário para registrar o baseline.
- Modificar: nenhum código nesta fase.
- Verificar: banco operacional, logs, lotes e relatórios existentes.

Passos:

- [ ] Registrar por 14 e 30 dias: envios por canal, marketplace, categoria, família/título normalizado, repetição e intervalo entre envios.
- [ ] Registrar ofertas elegíveis atuais por marketplace/categoria e distribuição do candidate pool.
- [ ] Registrar taxa de `CurationRun` concluída, falha, selecionadas/candidatas e lotes `ready/sent`.
- [ ] Registrar o conteúdo sanitizado do `observer_context_json` mais recente.
- [ ] Criar um relatório baseline JSON/Markdown fora dos artefatos públicos, contendo somente agregados e IDs internos locais quando necessários para análise.
- [ ] Fixar métricas de comparação: repetição em 7 dias, repetição em 30 dias, famílias distintas, marketplace distribution, categorias distintas, taxa de candidatos desconhecidos e ofertas novas.

Gate: o baseline deve ser reproduzível e não pode conter texto bruto, URLs de terceiros, JIDs, remetentes, tokens ou segredos.

---

## Fase 1 — Cooldown, reentrada e penalidade de recorrência

**Objetivo:** impedir que a mesma oferta/família domine ciclos consecutivos sem bloquear melhorias reais.

**Arquivos prováveis:**

- Modificar: `apps/curation/services/selector.py`
- Modificar: `apps/distribution/services/delivery.py`
- Modificar ou criar: `apps/curation/services/recurrence.py`
- Modificar: `apps/curation/services/quality_score.py`
- Modificar: `apps/curation/services/settings.py` se as configurações forem armazenadas como Settings
- Testar: `apps/curation/tests/test_selector.py`
- Testar: `apps/distribution/tests/` relacionado a `_should_republish_after_improvement`

Implementação:

- [ ] Definir configuração explícita, com defaults seguros:
  - cooldown normal por canal: 72 horas;
  - cooldown de família saturada: 120 horas;
  - janela de recorrência: 30 dias;
  - limite recomendado de reentradas por família: 2 em 30 dias;
  - melhoria material de preço: queda mínima configurável, inicialmente 10% ou valor absoluto mínimo definido a partir do baseline;
  - reentrada por cupom: somente quando houver código/regra real validada, nunca pelo token genérico `CUPOM`.
- [ ] Criar função pura `get_offer_recurrence_signal(offer, channel, now=None)` retornando contagem de envios, último envio, família normalizada, cooldown restante e motivo de bloqueio/penalidade.
- [ ] Definir família por `produto_canonico_id` quando disponível e, como fallback, tokens normalizados do título, removendo marca, cor, voltagem, tamanho e termos genéricos quando apropriado.
- [ ] Integrar a regra com a elegibilidade por canal usando subquery ou IDs pré-calculados, evitando o problema de `exclude()` em relações reversas múltiplas.
- [ ] Separar três estados: `blocked_cooldown`, `penalized_recurrence` e `eligible_after_improvement`.
- [ ] Aplicar penalidade no score, não remoção definitiva, para famílias recorrentes que ainda podem ser comercialmente relevantes.
- [ ] Preservar a regra atual de reentrada por melhoria material e fazê-la funcionar com preço, cupom validado ou mudança significativa de condição comercial.
- [ ] Adicionar logs agregados: quantidade bloqueada por cooldown, penalizada por recorrência, reentrada por melhoria e famílias mais saturadas; não registrar conteúdo bruto de grupos terceiros.

Testes obrigatórios:

- oferta enviada ontem fica fora do pool;
- oferta enviada há mais de 72 horas volta a ser elegível se não estiver saturada;
- queda de preço material permite reentrada;
- cupom validado permite reentrada;
- `CUPOM` genérico não permite reentrada;
- duas ofertas de vendedores diferentes da mesma família sofrem a mesma regra;
- envio em Telegram não bloqueia indevidamente o WhatsApp;
- falha de envio não é contada como envio bem-sucedido;
- lote `ready` pendente continua bloqueando duplicação;
- uma oferta com envio em outro canal e falha no canal atual permanece elegível no canal atual.

Gate: focused tests pass, `manage.py check` passa, nenhuma mudança de produção/timer.

---

## Fase 2 — Baixa prioridade editorial para spinning, livros e genéricos

**Objetivo:** reduzir saturação sem transformar categorias inteiras em blacklist.

**Arquivos prováveis:**

- Modificar: `apps/curation/services/baseline_snapshot.py`
- Modificar: `apps/curation/services/quality_score.py`
- Modificar: `apps/curation/services/hermes_runner.py`
- Modificar: `apps/curation/services/ai_prompt.py`
- Modificar: `apps/curation/services/selector.py`
- Modificar: `apps/curation/services/classifier.py` se a classificação atual não distinguir as famílias
- Testar: `apps/curation/tests/test_quality_score.py`
- Testar: `apps/curation/tests/test_hermes_runner.py`
- Testar: `apps/curation/tests/test_selector.py`

Implementação:

- [ ] Adicionar flags editoriais, sem blacklist automática:
  - `low_priority_spinning`;
  - `low_priority_book`;
  - `low_priority_generic`;
  - `recurrence_saturated_family` quando o histórico atingir o limite configurado.
- [ ] Classificar spinning por termos normalizados: `spinning`, `bicicleta ergometrica`, `bike indoor`, `bicicleta de ciclismo indoor` e equivalentes.
- [ ] Classificar livros por `livro`, `livros`, `capa comum`, `capa dura`, `kindle`, `ebook` e equivalentes.
- [ ] Classificar genéricos por ausência de marca, título excessivamente genérico, baixa diferenciação e sinais de variação não confiável.
- [ ] Aplicar penalidade limitada ao score e instruir a IA a usar esses itens apenas como preenchimento quando faltarem opções melhores.
- [ ] Manter exceção para melhoria material, marca forte, alta demanda observada, cupom validado e produto claramente diferente.
- [ ] Garantir que o texto de saída não exponha os nomes técnicos das flags.
- [ ] Adicionar métrica de quantos itens de baixa prioridade entraram no candidate pool, foram selecionados e foram enviados.

Gate: em lote de homologação, a quantidade de spinning cai fortemente sem zerar a categoria, e livros/genéricos deixam de ocupar slots prioritários quando existirem alternativas melhores.

---

## Fase 3 — Radar de busca baseado no observer

**Objetivo:** transformar observações agregadas em sinais acionáveis de captura e curadoria.

**Arquivos prováveis:**

- Modificar: `apps/curation/services/observer_context.py`
- Criar ou modificar: `apps/marketplaces/services/search_radar.py`
- Modificar: `scrapers/category_targets.py`
- Modificar: `apps/curation/services/ai_prompt.py`
- Modificar: `apps/curation/services/baseline_snapshot.py`
- Modificar: `apps/curation/management/commands/prepare_ai_curation_batch.py`
- Testar: `apps/curation/tests/test_observer_context.py`
- Criar/testar: `apps/marketplaces/tests/test_search_radar.py`
- Testar: `apps/curation/tests/test_prepare_ai_curation_batch_command.py`

Implementação:

- [ ] Definir estrutura sanitizada `SearchRadarSnapshot` com:
  - `brands`;
  - `categories`;
  - `price_bands`;
  - `marketplaces`;
  - `coupon_signals`;
  - `uncovered_opportunities`;
  - contagens e janela de observação.
- [ ] Separar `CUPOM` de códigos reais; o primeiro será somente prevalência e os demais deverão passar por validação.
- [ ] Normalizar marcas e categorias com acentos, caixa, abreviações e aliases.
- [ ] Cruzar observer com `Offer` para identificar sinais recorrentes sem oferta própria equivalente ou sem envio recente.
- [ ] Usar o radar para ordenar targets e enriquecer o candidate pool; não permitir que o radar publique diretamente uma oferta.
- [ ] Manter marketplaces desconhecidos como sinal de gap de identificação, não como marketplace elegível para balanceamento.
- [ ] Expor no relatório interno a cadeia completa: observada → encontrada → elegível → candidata → selecionada → enviada.
- [ ] Manter dados brutos, URLs, JIDs, remetentes e cópias de terceiros fora do snapshot e do prompt.

Gate: gerar snapshot com dados reais em diretório temporário e comprovar que a sanitização rejeita URLs, JIDs, texto bruto, hashes de texto de concorrentes e chaves sensíveis.

---

## Fase 4 — Catálogo ampliado de buscas e targets

**Objetivo:** ampliar descoberta com marcas de maior intenção comercial sem abandonar categorias gerais.

**Arquivos prováveis:**

- Modificar: `scrapers/category_targets.py`
- Criar, se necessário: `scrapers/search_targets.py`
- Modificar: `scrapers/mercado_livre.py`, `scrapers/amazon.py` ou adaptadores específicos somente onde houver suporte real a busca por termo
- Modificar: `scrapers/shopee.py` somente se a API/collector suportar o target de modo seguro
- Testar: `apps/marketplaces/tests/test_category_targets.py`
- Testar: testes dos scrapers alterados

Implementação:

- [ ] Separar targets declarativos em `base_categories`, `priority_brands` e `radar_terms`.
- [ ] Adicionar os blocos de marcas definidos neste plano, com limites por marketplace/categoria/ciclo.
- [ ] Adicionar termos derivados para suplementos: `whey`, `creatina`, `pre treino`, `barra proteica`, `vitaminas`, sem depender apenas da marca.
- [ ] Adicionar termos para perfumes árabes: `perfume arabe`, `eau de parfum`, `lattafa`, `afnan`, `armaf`, `rasasi`, `maison alhambra` e aliases.
- [ ] Adicionar Insider como target explícito de moda masculina e básica, com variações de produto.
- [ ] Preservar os targets de categoria existentes como fallback.
- [ ] Aplicar ciclo/limite por família para evitar que a ampliação de marcas aumente volume sem diversidade.
- [ ] Não implementar busca por keyword em marketplace que só possui endpoint categorial sem validar o contrato real; nesse caso, usar a marca como prioridade de classificação/ranking.
- [ ] Manter filtros de preço, desconto, imagem, link, variação e segurança de cada marketplace.
- [ ] Revisar o filtro da Shopee para distinguir variação legítima de preço inseguro, sem simplesmente remover a proteção.

Gate: dry-run dos scrapers mostra aumento de itens novos e diversidade de marcas, sem aumento proporcional de duplicatas ou produtos genéricos.

---

## Fase 5 — Candidate pool balanceado e lote de homologação

**Objetivo:** garantir que o lote novo receba candidatos suficientes e equilibrados antes da decisão da IA.

**Arquivos prováveis:**

- Modificar: `apps/curation/management/commands/prepare_ai_curation_batch.py`
- Modificar: `apps/curation/services/batch_optimizer.py` somente se a verificação encontrar perda de marketplace após a decisão IA
- Modificar: `apps/curation/services/ai_prompt.py`
- Testar: `apps/curation/tests/test_prepare_ai_curation_batch_command.py`
- Testar: `apps/curation/tests/test_batch_optimizer.py`

Implementação:

- [ ] Processar o pool completo elegível antes de criar o preview limitado.
- [ ] Construir pool balanceado por marketplace, usando quotas iniciais próximas da configuração atual, mas preenchendo shortages com segurança.
- [ ] Preservar a IA como curadora: somente decisões `selected_for_batch=true` entram no lote.
- [ ] Recalcular `actual_distribution_json` a partir dos itens persistidos, nunca confiar em contagem inventada pelo modelo.
- [ ] Garantir pelo menos um candidato Shopee/Amazon quando houver candidato elegível e a quota permitir, sem promover candidato inseguro.
- [ ] Expor no relatório: pool total, pool por marketplace, preview, selecionadas, descartes por recorrência, descartes por baixa prioridade e itens enviados anteriores.
- [ ] Gerar lote `homolog` com `--runner mock`, `--skip-images` e diretórios temporários de auditoria/público.
- [ ] Não gerar lote `production` nesta fase.

Comando de referência:

```bash
set -a
. ./.env
set +a
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch \
  --channel whatsapp_principal \
  --mode homolog \
  --runner mock \
  --candidate-limit 50 \
  --skip-images \
  --audit-dir /tmp/descontos-homolog-audit \
  --public-dir /tmp/descontos-homolog-public
```

Gate: lote persistido como `homolog`, sem envio externo, com marketplace distribution e itens selecionados verificáveis no banco.

---

## Fase 6 — Comparação baseline versus lote novo

**Objetivo:** decidir com evidência se a alteração melhora o produto.

**Arquivos prováveis:**

- Criar: `scripts/compare_curation_batches.py` ou comando Django equivalente
- Criar: teste do comparador
- Criar: relatório temporário em `/tmp/descontos-homolog-comparison/`
- Não alterar: JSON público versionado

Comparar:

- total de candidatos e selecionados;
- distribuição por marketplace;
- distribuição por categoria;
- marcas distintas;
- famílias distintas;
- número de spinning, livros e genéricos;
- taxa de itens repetidos em 7 e 30 dias;
- taxa de itens novos;
- itens observados pelo radar que chegaram ao pool;
- itens do radar encontrados, mas ainda não elegíveis;
- falhas da IA e tempo de execução;
- quantidade de slots preenchidos por fallback.

Critérios mínimos sugeridos para aprovação:

- queda de pelo menos 50% na presença de famílias repetidas no lote;
- no máximo um item por família equivalente no mesmo lote;
- redução clara da participação de spinning sem zerar a categoria;
- livros e genéricos somente quando existirem poucos candidatos melhores;
- aumento de marcas/categorias distintas;
- nenhum marketplace elegível desaparecer por erro do candidate pool;
- zero vazamento de dados sensíveis no JSON de auditoria/público;
- `CurationRun` homolog concluído sem envio real.

Se algum critério falhar, corrigir a fase correspondente e repetir o lote. Não promover por impressão visual.

---

## Fase 7 — Promoção controlada para produção

**Objetivo:** promover somente o código validado e medir o primeiro ciclo real com risco limitado.

Pré-condições obrigatórias:

- branch validada e baseada no `origin/main` atual;
- focused tests, `manage.py check` e `makemigrations --check --dry-run` aprovados;
- comparação baseline versus novo aprovada;
- nenhum arquivo gerado/runtime indevido no commit;
- lote `production/ready` antigo inspecionado e não contaminado por repetição;
- janela de silêncio respeitada;
- Evolution Adapter e instância de envio saudáveis;
- autorização explícita para o smoke test de produção.

Passos:

- [ ] Rebase/integração da branch validada sobre o remoto atual.
- [ ] Reexecutar todos os gates após rebase.
- [ ] Fazer commit apenas dos arquivos de código, testes e documentação autorizados.
- [ ] Publicar/push somente após autorização de promoção.
- [ ] Reiniciar o processo longo `run_bot` somente após confirmar o checkout/interpreter usados pelo systemd.
- [ ] Preparar lote pequeno de produção, inicialmente até 3 itens, com o profile real.
- [ ] Verificar persistência do `CuratedBatch`, status, itens e deliveries.
- [ ] Consumir somente após confirmar canal, modo, expiração e janela BRT.
- [ ] Verificar IDs externos, status de cada entrega, ausência de falhas e saúde do adapter.
- [ ] Comparar o primeiro ciclo real com o baseline, sem alterar cadência ainda.

Comando de referência para primeiro lote, somente com autorização de produção:

```bash
set -a
. ./.env
set +a
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python manage.py prepare_ai_curation_batch \
  --channel whatsapp_principal \
  --mode production \
  --runner real \
  --profile descontos-bot \
  --candidate-limit 3 \
  --skip-images \
  --audit-dir /tmp/descontos-production-audit \
  --public-dir /tmp/descontos-production-public
```

O consumo real não faz parte automática deste plano; será um gate operacional separado, após inspeção do lote.

---

## Verificação técnica consolidada

Executar no checkout real, com `.env` carregado sem imprimir segredos:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m pytest \
  apps/curation/tests/test_selector.py \
  apps/curation/tests/test_quality_score.py \
  apps/curation/tests/test_observer_context.py \
  apps/curation/tests/test_prepare_ai_curation_batch_command.py \
  apps/curation/tests/test_batch_optimizer.py -v --tb=short
```

Também executar:

- testes dos scrapers e targets alterados;
- migração em cópia isolada do SQLite, quando houver alteração de model;
- script temporário `/tmp/hermes-verify-*.py` para AST, sanitização, comparação e limpeza;
- inspeção do lote persistido no banco, não apenas stdout;
- validação de JSON sem URLs/JIDs/texto bruto/segredos;
- `git diff --check`, `git status`, branch e divergência remota.

---

## Rollback

- A alteração deverá ser feita em branch/worktree isolado.
- Antes da implementação, criar checkpoint Git `backup/pre-commercial-search-20260812` a partir do HEAD de trabalho.
- Não alterar banco de produção durante as fases 0–6.
- Configurações novas devem possuir defaults compatíveis e possibilidade de desativação.
- Em caso de piora, desativar penalidades/configurações, restaurar a branch anterior e manter o baseline para comparação.
- Não apagar banco, logs, sessões WhatsApp ou artefatos gerados.
- Não force-pushar `main`.

## Decisões ainda abertas durante a execução

1. Confirmar se cooldown inicial de 72 horas e saturação de 120 horas são adequados ao baseline ou se precisam de ajuste.
2. Confirmar o limiar de melhoria material de preço com base na distribuição real.
3. Confirmar quais marketplaces suportam busca efetiva por keyword/brand sem violar o contrato dos scrapers.
4. Confirmar quotas finais por marketplace após observar pool e cliques; não alterar apenas por preferência teórica.
5. Confirmar se suplementos serão expostos em todos os canais ou permanecerão com quota limitada.

Essas decisões devem ser resolvidas na homologação por evidência, não por alteração direta em produção.

## Critério final de conclusão

O plano só será considerado concluído quando houver:

- código validado em branch isolada;
- testes focados aprovados;
- lote homolog persistido e inspecionado;
- comparação baseline versus novo com melhoria objetiva;
- ausência de envio/publicação durante as fases de implementação;
- autorização separada para promoção e smoke test real;
- verificação posterior das linhas persistidas e do adapter após eventual produção.
