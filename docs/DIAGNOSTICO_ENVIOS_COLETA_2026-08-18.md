# Diagnóstico — consistência de envios + coleta de ofertas (2026-08-18)

> Documento vivo. Nasceu de um diagnóstico completo do projeto (3 agentes de exploração +
> verificação direta de código, systemd e Hermes) e virou **plano de execução por ondas**,
> salvo dentro do repositório para poder ser executado em partes, em sessões diferentes,
> sem precisar reler o histórico de conversa.
>
> A seção [Registro de execução](#registro-de-execução) no fim é a fonte da verdade sobre
> o que já foi feito. **Atualize-a a cada item concluído.**

---

## Achado #0 — correção urgente de contexto (não é bug de código)

Os dois alertas do Hermes criados numa sessão anterior — **"Saúde sessão ML"** e
**"Resumo Market Intel"** — **não existem mais** no perfil ativo do Hermes. Sumiram numa
migração v1→v2 da infraestrutura pessoal em **2026-08-01**, fora deste repositório.
Última execução registrada: 2026-07-31 / 2026-08-01.

Isso invalida um relatório anterior que dizia que os dois jobs estavam "criados e ativos".
Os scripts originais foram preservados em
`~/.hermes_migration_backups/20260730_143306/scripts/`.

Ação: avulsa, de operação — ver [C1](#c1--jobs-hermes-mortos).

---

## Parte A — consistência de envios

### A1 — `processar_fila_envio` existe, é testado e **nunca roda** · severidade ALTA

Todo o subsistema de retry/backoff/dead-letter de `Delivery` está pronto:

- `apps/distribution/services/fila_envio.py` — backoff exponencial `2**retry_count` min
  (teto 60min), `MAX_RETRIES=5`, dead-letter com alerta, pré-check único da sessão do
  WhatsApp, teto de idade de 72h (não reenvia oferta velha com preço desatualizado).
- `apps/distribution/management/commands/processar_fila_envio.py` — comando pronto, com
  `--dry-run` e `--limit`.
- Suíte de testes de 428 linhas cobrindo o módulo.

**Mas não existe nenhuma unit systemd que o dispare.** Na prática, qualquer `Delivery`
que entra em `FAILED` fica lá parada para sempre: nunca é reenviada e nunca chega a
dead-letter (logo, nunca gera o alerta de dead-letter que o próprio módulo implementa).

### A2 — queda de sessão do WhatsApp não alerta ninguém · severidade ALTA

`SessaoIndisponivelError` interrompe o lote em 3 pontos, e em todos eles o tratamento é
apenas `self.stdout.write` + `log.error` — ninguém é avisado:

| Arquivo | Linhas | Contexto |
|---|---|---|
| `apps/orchestration/management/commands/run_bot.py` | ~352-360 | fluxo legado (`deliver_offer_to_channel`) |
| `apps/orchestration/management/commands/run_bot.py` | ~470-478 | fluxo de curadoria IA (`deliver_curated_item_to_whatsapp`) |
| `apps/orchestration/management/commands/consumir_fila_whatsapp.py` | ~129-137 | consumo da fila desacoplada |

Os **pré-checks** têm o mesmo problema (`run_bot._check_whatsapp_session` ~501-524,
`consumir_fila_whatsapp._check_whatsapp_session` ~188-211): abortam o ciclo em silêncio.

Existe `apps/analytics/services/alertas.py::enviar_alerta_operador()` — função central,
já usada por scraper/curadoria/dead-letter, que nunca lança exceção. Só falta chamá-la.

Efeito prático: a sessão cai, o bot para de enviar, e só se descobre olhando log.

### A3 — lote expirado com itens pendentes · severidade MÉDIA (Onda 3)

`CuratedBatch.status` declara `CONSUMING` e `EXPIRED`, mas **nenhum código atribui esses
dois valores**. Um lote `READY` cujos itens nunca foram consumidos fica `READY` para
sempre, sem alerta e sem expiração.

### A4 — healthcheck escrito e nunca lido · severidade MÉDIA (Onda 3)

`run_bot` grava `data/last_cycle.txt` a cada ciclo, mas **nada lê esse arquivo**. Os
únicos comandos `check_*_health` do projeto são `check_observer_health`,
`check_ml_cookie_health` e `check_instagram_composio`. Se o `run_bot` travar, ninguém
percebe por estagnação.

---

## Parte B — coleta de ofertas

> **B1 e B2 nasceram do mesmo commit**: `84e5071` — *"feat: execute directed commercial
> search queries"* (2026-08-12). Verificado com
> `git log --all -p -S"lista.mercadolivre" -- scrapers/mercado_livre.py`.

### B1 — filtros de categoria inertes + fallback truncado · severidade ALTA

Em `apps/scraping/services/adapters.py::collect()`:

```python
def collect(self, max_pages: int) -> list[dict]:
    directed = self._directed_queries()
    payloads: list[dict] = []
    if directed and hasattr(self.scraper, 'scrape_search_queries'):
        payloads.extend(self.scraper.scrape_search_queries(directed))          # (1)
    if not payloads and _category_scraping_enabled() and hasattr(self.scraper, 'scrape_categories'):
        targets = flatten_urls(self.marketplace_code)
        if targets:
            payloads.extend(self.scraper.scrape_categories(
                [... for t in targets[:DIRECTED_FALLBACK_CATEGORY_LIMIT]],     # (2)
            ))
            return _apply_category_filters(...)                                # (3)
    if payloads:
        return _mark_unattributed_as_fallback(_deduplicate_payloads(payloads)) # (1) sai por aqui
    return _mark_unattributed_as_fallback(self.scraper.scrape_daily_deals(max_pages=max_pages))
```

Três problemas encadeados:

1. **`_apply_category_filters` só roda no ramo (3)** — o de `scrape_categories`. O caminho
   que de fato executa hoje é o (1), busca direcionada, que sai pelo `return` de baixo
   **sem passar por filtro nenhum**. Todo o controle de qualidade por categoria
   (`min_discount`, `max_price`, `cycle_limit` — incluindo o teto de suplementos) está
   inerte no caminho real.
2. **`DIRECTED_FALLBACK_CATEGORY_LIMIT = 2`** trunca `flatten_urls()` sempre nas **2
   primeiras URLs**, na mesma ordem, todo ciclo. Categorias no fim da lista
   (ex. `moda_masculina`, `saude_suplementacao`) são inalcançáveis por construção.
3. **`category_scraping_enabled`**: o default do código é `0` (desligado), mas o valor
   real no banco é **`'1'`** (verificado em 2026-08-18 via
   `Setting.objects.filter(key='category_scraping_enabled')`). Ou seja, a flag **já está
   ligada** — mexer no default do código não teria efeito nenhum. O que trava o ramo de
   categoria não é a flag, é a condição `not payloads` (só cai no fallback se a busca
   direcionada voltar vazia) somada ao truncamento do item 2.

O log de resumo `category_scraping_summary` foi **removido** no mesmo commit `84e5071`,
o que apagou a visibilidade operacional de quantas ofertas cada categoria rendeu.

### B2 — busca direcionada do ML usa domínio bloqueado · severidade ALTA

`scrapers/mercado_livre.py:214`:

```python
items.append((f'Busca direcionada: {query.query_text}',
              f'https://lista.mercadolivre.com.br/{slug}', ...))
```

`lista.mercadolivre.com.br` é **bloqueado pelo Akamai** (fato conhecido do projeto).
`scrapers/category_targets.py:115-118` documenta a migração já feita para
`www.mercadolivre.com.br/ofertas?category=MLB...` — mas essa é URL de **categoria fixa**,
não de busca por texto livre.

Como `SearchQuery.query_text` é termo livre (marca/produto observado) e `category_code` é
opcional e frequentemente vazio (`apps/marketplaces/services/search_query_planner.py`),
**não há no código atual nenhuma URL `www.mercadolivre.com.br` equivalente para busca por
texto**. Resultado: a busca direcionada do ML volta vazia ou bloqueada — e como o fallback
de categoria está truncado (B1), o ML cai direto no `scrape_daily_deals` genérico.

### B3 — exceção engolida em silêncio · severidade MÉDIA

`apps/scraping/services/adapters.py:53-61`:

```python
except Exception:
    return ()
```

Qualquer falha em `build_search_radar`/`build_search_plan` desliga a busca direcionada
**sem deixar rastro**. O sistema degrada para o fallback genérico e nada indica o porquê.

### B4/B5 — backlog de médio prazo · severidade BAIXA

- **B4**: sem rotação de proxy/IP — todo o scraping sai do mesmo IP.
- **B5**: categorias de alto volume ainda não cobertas (Pet, Automotivo, Ferramentas,
  Papelaria, Livros, Games).

### B6 — lacuna de teste que deixou a regressão passar · severidade MÉDIA

`apps/scraping/tests/test_category_filters.py` testa `_apply_category_filters` **em
isolamento**, nunca a partir de `collect()`. Nenhum teste cobre o truncamento de
`flatten_urls`. Foi essa lacuna que permitiu B1 passar despercebida no commit `84e5071`.

---

## Parte C — infra e observabilidade

### C1 — jobs Hermes mortos

Ver [Achado #0](#achado-0--correção-urgente-de-contexto-não-é-bug-de-código).
Ação avulsa, fora do código.

### C2 — `descontos-bot-evolution-14h` bloqueado

Precisa de `hermes auth` para voltar a rodar. Ação avulsa, fora do código.

### C3 — pré-check de sessão · **já resolvido**

Resolvido em sprint anterior (`_check_whatsapp_session` em `run_bot` e
`consumir_fila_whatsapp`). Falta apenas o alerta — que é [A2](#a2--queda-de-sessão-do-whatsapp-não-alerta-ninguém--severidade-alta).

### C4 — logs sem rotação · severidade MÉDIA (Onda 3)

`logs/wa_service.out` tem **~507MB** (processo legado morto, última escrita 2026-05-29).
O `RotatingFileHandler` do Django só cobre `bot.log` (30MB × 7). Todas as units systemd
usam `StandardOutput=append:` — crescimento ilimitado. Estado atual:

| Arquivo | Tamanho | Última escrita |
|---|---|---|
| `logs/wa_service.out` | ~507 MB | 2026-05-29 (morto) |
| `logs/bot.log.2` | ~62 MB | 2026-07-20 |
| `logs/bot.log.1` | ~30 MB | 2026-08-13 |
| `logs/run_bot.nohup.log` | ~14 MB | 2026-07-29 (legado) |
| `logs/run-bot.log` | ~14 MB | ativo |

### C5 — ruído da janela de silêncio · severidade BAIXA (Onda 3)

`run_bot` loga o aviso de janela de silêncio (00:00–08:00 BRT) a cada ciclo, poluindo o
log justamente na faixa em que nada deveria acontecer.

### C6 — `loginctl linger` / autostart do Docker Desktop

Precisa de confirmação: se o `linger` não estiver ativo, os timers `--user` morrem ao
encerrar a sessão. O stack Evolution (`evolution_api`, `evolution_postgres`,
`evolution_redis`, `evolution_api-whatsapp-router-1`) vive num projeto **irmão**
(`../evolution_api/docker-compose.yml`) e virou stack multi-bot compartilhada
(`whatsapp-shared-router`) por volta de 2026-08-01. Mexe em configuração do SO — **não
alterar sem autorização explícita do dono**.

---

## Ondas

### Onda 1 — maior impacto / menor risco

- **A1** — criar `processar-fila-envio.service` + `.timer` (`~/.config/systemd/user/`),
  no padrão de `consumir-fila-whatsapp-v2`. **Auditar cadência (volume × intervalo) antes
  de habilitar** — é um timer que dispara envio real.
- **A2** — chamar `enviar_alerta_operador` (categoria `whatsapp_sessao_indisponivel`) nos
  3 catches de `SessaoIndisponivelError` e nos 2 pré-checks.
- **B2** — **verificar ao vivo** candidatos de URL de busca por texto em
  `www.mercadolivre.com.br` (com a sessão impersonada do próprio scraper) antes de trocar
  qualquer URL. Se nenhum funcionar: contenção documentada — ML não usa busca direcionada
  por texto livre, seguindo por categoria/daily deals; Amazon e Shopee mantêm a busca
  direcionada normalmente.
- **B3** — `log.warning(..., exc_info=True)` antes do `return ()` silencioso.

### Onda 2 — correção estrutural da coleta (escopo amplo, decidido pelo dono)

- **B1** — aplicar `_apply_category_filters` também aos payloads da busca direcionada;
  remover/aumentar substancialmente `DIRECTED_FALLBACK_CATEGORY_LIMIT`; repor o log
  `category_scraping_summary`.
  > Executado em 2026-08-19 com uma correção de rumo: o primeiro item, sozinho, seria
  > no-op. A decisão do dono foi trocar o fallback por **união** dos dois caminhos de
  > coleta. Ver o histórico do B1 no registro de execução.
- Testes: cobrir `_apply_category_filters` a partir do ramo direcionado; novo teste de
  não-truncamento (fecha a lacuna B6); verificação manual em dry-run de que categorias
  antes inatingíveis rendem `kept > 0`.

### Onda 3 — registrada, **não** implementada neste pass

A3, A4, C4, C5, B4/B5 — ver descrições acima.

### Fora do escopo de código (ação avulsa, não executada automaticamente)

C1, C2, C6.

---

## Verificação end-to-end

- Suíte: `python3 manage.py test apps.distribution apps.orchestration apps.scraping` após
  cada onda.
- **Onda 1**: `systemctl --user list-timers` mostrando `processar-fila-envio.timer` ativo;
  1 execução manual em `--dry-run` conferindo o log; alerta de sessão validado por teste
  automatizado (nunca simulando queda em produção).
- **Onda 2**: coleta manual em dry-run nos 3 marketplaces, conferindo no log
  (`category_scraping_summary` restaurado) que categorias antes inatingíveis aparecem com
  `kept > 0`.
- Documento commitado no repo. **Sem `git push` a menos que o dono peça.**

---

## Registro de execução

Formato de cada entrada: **item · data · o que foi feito · arquivos tocados · resultado da
verificação · pendências residuais**.

| Item | Status | Data | Observação |
|---|---|---|---|
| Doc criado no repo | feito | 2026-08-18 | `docs/DIAGNOSTICO_ENVIOS_COLETA_2026-08-18.md`. Valores de `Setting` e tamanhos de log conferidos no ambiente real antes de escrever. |
| A1 — timer `processar_fila_envio` | feito | 2026-08-19 | Habilitado com autorização do dono. `enabled`/`active`, 1ª execução real exit 0 (0 elegíveis), próximo disparo agendado. |
| A2 — alerta sessão WhatsApp caída | feito | 2026-08-18 | 3 catches + 2 pré-checks chamando `enviar_alerta_operador`. Teste novo cobrindo os 5 caminhos. |
| B2 — domínio bloqueado busca ML | feito | 2026-08-18 | Verificação ao vivo de 5 candidatos de URL; nenhum serve. Contenção adotada: ML não faz busca direcionada por texto. |
| B3 — log de exceção silenciosa | feito | 2026-08-18 | `log.warning(..., exc_info=True)` antes do `return ()`, com teste. |
| B1 — filtros de categoria na busca direcionada + destravar fallback | feito | 2026-08-19 | Coleta virou **união** (direcionada + categoria sempre), truncamento removido, log reposto. Dry-run real nos 3 marketplaces confirmou `kept > 0` em todas as categorias antes inatingíveis. |
| B7 — busca direcionada da Shopee quebrada (GraphQL) | pendente (achado novo) | 2026-08-19 | Descoberto no dry-run do B1. 6/6 queries falham; ver histórico. |
| B8 — queries de `radar_category` sem sentido comercial | pendente (achado novo) | 2026-08-19 | `faixa preco:ate 100` vira termo de busca literal; ver histórico. |
| A3 — alerta de lote expirado | pendente (Onda 3, backlog) | — | — |
| A4 — health check de estagnação do run_bot | pendente (Onda 3, backlog) | — | — |
| C4 — limpeza/rotação de log | pendente (Onda 3, backlog) | — | — |
| C5 — ruído de log da janela de silêncio | pendente (Onda 3, backlog) | — | — |
| B9 — radar de concorrente (observer como fonte de coleta) | feito, desligado | 2026-08-21 | Fecha a lacuna de alcance que sobrou do B2. Ver `docs/RADAR_CONCORRENTE_2026-08-21.md`. Medido: 17 anúncios inéditos em 24h. Publicação depende de `competitor_radar_enabled=true` **e** de reiniciar o `run-bot`. |
| B4/B5 — proxy/IP, novas categorias | pendente (backlog médio prazo) | — | — |
| C1/C2/C6 — Hermes morto, hermes auth, linger/docker | pendente (ação avulsa, fora do código) | 2026-08-19 | Parte do C6 esclarecida sem mexer em nada: `Linger=yes` (timers `--user` sobrevivem ao fim da sessão). Resto em aberto. |
| Falha pré-existente `test_publish_telegram_ai_curation` | pendente (fora do escopo deste plano) | 2026-08-18 | Reproduz em `HEAD` limpo (854c7e6); não é regressão da Onda 1. Ver histórico. |

### Histórico detalhado

<!-- Uma entrada por item concluído. Não apagar entradas antigas. -->

### A1 — timer `processar_fila_envio` · 2026-08-18 · **parcial**

- **Feito**: `scripts/processar-fila-envio.service` + `.timer` criados no padrão de
  `consumir-fila-whatsapp-v2`, e copiados para `~/.config/systemd/user/` (conteúdo
  idêntico ao do repo, conferido com `diff`).
- **Auditoria de cadência antes de habilitar** (exigência do próprio plano): ~40-130
  `Delivery` criadas/dia, 118 nas últimas 72h, 0 elegíveis para retry no momento, 0 com
  `retry_count > 0`, nenhum dead-letter desde 2026-06-25. Decisão: `--limit 5` por disparo
  + `OnUnitActiveSec=30min` + `RandomizedDelaySec=10min` → pior caso sustentado ~10
  envios/hora. O racional está comentado dentro das próprias units.
- **Dry-run manual**: executado, `logs/processar-fila-envio.log` registra
  `Nenhuma Delivery elegível para retry no momento (0 elegíveis)`.
- **Habilitado em 2026-08-19**, com autorização explícita do dono (é timer de envio real,
  por isso não foi ligado junto com a criação das units):
  `systemctl --user daemon-reload && systemctl --user enable --now processar-fila-envio.timer`
  → symlink criado em `timers.target.wants/`, estado `enabled`/`active`.
- **1ª execução real**: disparou na hora (`OnBootSec=10min` + `Persistent=true`, com o
  sistema já ligado há mais tempo que isso), `exit 0`, log
  `Nenhuma Delivery elegível para retry no momento (0 elegíveis)` — nenhuma mensagem
  enviada. Próximo disparo agendado normalmente pelo `OnUnitActiveSec=30min`.
- **Bônus de verificação (C6)**: `loginctl show-user marce` → `Linger=yes`. Ou seja, os
  timers `--user` **não** morrem ao encerrar a sessão — a dúvida levantada em C6 sobre o
  `linger` está resolvida (a parte do autostart do Docker Desktop continua em aberto).

### A2 — alerta de sessão do WhatsApp caída · 2026-08-18 · feito

- `run_bot.py`: alerta nos 2 catches de `SessaoIndisponivelError` (fluxo legado ~358 e
  curadoria IA ~482) e no pré-check `_check_whatsapp_session` (ambos os ramos: exceção do
  cliente e `not status.connected`).
- `consumir_fila_whatsapp.py`: mesmo tratamento no catch do consumo do lote e nos 2 ramos
  do pré-check.
- Todos usam `enviar_alerta_operador(..., categoria='whatsapp_sessao_indisponivel')`, com
  mensagem dizendo o que ficou pendente (ofertas seguem elegíveis / itens seguem pendentes
  no lote).
- **Teste**: `apps/orchestration/tests/test_whatsapp_session_alerts.py` (243 linhas),
  cobrindo os 5 caminhos sem simular queda em produção. Criados também os
  `apps/orchestration/tests/__init__.py` e `apps/distribution/tests/__init__.py`, e
  `apps/distribution/tests.py` virou `apps/distribution/tests/test_whatsapp_delivery.py`.

### B2 — busca direcionada do ML em domínio bloqueado · 2026-08-18 · feito (contenção)

Verificação **ao vivo**, com a sessão impersonada real do scraper, dos candidatos de URL:

| Candidato | Resultado |
|---|---|
| `lista.mercadolivre.com.br/{slug}` sem cookie | 200 com ~10KB e zero cards, ou redirect para `/gz/account-verification` |
| `www.mercadolivre.com.br/jm/search?as_word=` | redirect para `/gz/account-verification` |
| `www.mercadolivre.com.br/search?q=` | 404 |
| `www.mercadolivre.com.br/ofertas?q=` | 200 com 45 cards, mas o `q` é **ignorado** — títulos idênticos aos de `/ofertas` sem `q`, para qualquer termo. Falso positivo perigoso |
| `lista.mercadolivre.com.br/{slug}` **com** `ML_COOKIE` | 200, 964KB, `<title>Cafeteira \| Mercado Livre</title>` (busca certa!), mas **zero** cards: virou React streaming SSR (`_n.ctx`, `$RC(...)`), sem `__PRELOADED_STATE__`, sem `ld+json`, sem `.poly-card` |

Nenhum serve. Contenção adotada (a que o plano já previa): `scrape_search_queries` retorna
`[]` com `log.warning('ml_directed_search_skipped ...')`, e o adapter cai no fallback de
categoria/daily deals, que funciona. Amazon e Shopee seguem com busca direcionada normal.
`_scrape_search_urls` foi removido (só era usado por esse caminho). Testes de
`test_directed_scrapers.py` atualizados para a nova expectativa.

> Extrair da página autenticada exigiria navegador headless ou engenharia reversa do
> payload de streaming — outro scraper, não um ajuste de URL. Fica como opção futura.

### B3 — exceção engolida em `_directed_queries` · 2026-08-18 · feito

`log.warning('directed_queries_failed marketplace=%s', ..., exc_info=True)` antes do
`return ()`, com teste em `test_directed_search_adapter.py` que força
`build_search_radar` a explodir e afirma que a mensagem e o motivo aparecem no log.

### Verificação da Onda 1 · 2026-08-18

`python3 manage.py test apps.distribution apps.orchestration apps.scraping` →
**105 testes, 1 falha**:
`test_publish_telegram_ai_curation.PublishTelegramAICurationTests.test_ai_curation_without_ready_batch_pauses_without_selector_fallback`.

**Falha pré-existente, não causada por esta onda** — confirmado stashando todas as
alterações de `apps/` e `scrapers/` e reproduzindo a falha em `HEAD` (854c7e6) limpo. É
sobre o `publish_telegram` preparar um lote de curadoria quando o teste espera a pausa
com "Nenhum lote curado pronto"; não toca nenhum arquivo desta onda. Fica registrada como
pendência separada.

### B1 — filtros de categoria + destravamento do fallback · 2026-08-19 · feito

**Correção de rumo antes de codar.** O plano previa "aplicar `_apply_category_filters`
também aos payloads da busca direcionada". Verificando o radar real, isso sozinho seria
**no-op**: o `category_code` das queries direcionadas vem como `'categoria:moda'` /
`'faixa_preco:ate_100'`, que não batem com os códigos de `category_targets`
(`moda_feminina`, `casa_cozinha`…), e os payloads da direcionada não têm `category_hint`
nenhum — logo `_apply_category_filters` os deixaria passar intocados de qualquer jeito.

O problema real era a **estrutura de fallback**: a categoria só rodava quando a direcionada
voltava vazia (`if not payloads`). Onde a direcionada funciona (Amazon), o ramo de
categoria nunca mais rodou desde 84e5071 — e com ele foram junto todas as regras de
qualidade. Decisão do dono (2026-08-19): **união** — os dois caminhos rodam sempre e o
resultado é mesclado.

O que mudou em `apps/scraping/services/adapters.py`:

1. `collect()` roda direcionada **e** categoria todo ciclo, mescla, deduplica e aplica
   `_apply_category_filters` numa única saída. `scrape_daily_deals` continua como último
   recurso, só quando os dois voltam vazios.
2. `DIRECTED_FALLBACK_CATEGORY_LIMIT` **removido** — todas as URLs de `flatten_urls()` são
   varridas (13 amazon / 8 ml / 14 shopee, contra 2 fixas antes).
3. `_deduplicate_payloads` passou a **mesclar** duplicatas em vez de descartá-las: a mesma
   oferta agora pode chegar pelas duas vias, e cada uma traz um sinal exclusivo
   (`search_provenance` da direcionada, `category_hint` da categoria). Mantém a primeira
   ocorrência e completa só os campos que faltam.
4. `category_scraping_summary` **reposto** (agora com `in=` além de `kept=`), e novo
   `collect_summary marketplace=… directed=… category=… total=…` para separar a
   contribuição de cada caminho.

**Testes** — nova classe `CategoryUnionCollectTests` em `test_directed_search_adapter.py`,
5 casos, fechando a lacuna B6 (os filtros passam a ser exercitados **a partir de
`collect()`**, não só em isolamento): união dos dois caminhos; não-truncamento (compara com
`len(flatten_urls('amazon'))`, então quebra de novo se o corte voltar); regras de categoria
+ log de resumo; dedup preservando os sinais das duas vias; `scrape_daily_deals` como
último recurso.

**Dry-run real nos 3 marketplaces** (sem gravar no banco), 2026-08-19:

| Marketplace | Páginas | Coletado | Mantido | `kept` por categoria |
|---|---|---|---|---|
| amazon | 19 (6 direcionada + 13 categoria) | 420 | 166 | casa_cozinha 9, moda_feminina 20, **moda_masculina 20**, infantil 15, tecnologia 20, beleza 15, **saude_suplementacao 5** |
| mercadolivre | 8 (direcionada pulada pelo B2) | 277 | 111 | casa_cozinha 25, infantil 15, tecnologia 20, beleza 15 |
| shopee | 28 | 254 | 120 | casa_cozinha 25, tecnologia 20, beleza 15, moda_feminina 20, **moda_masculina 20**, infantil 15, **saude_suplementacao 5** |

Nenhum marketplace bloqueado, nenhum CAPTCHA. As duas categorias que o diagnóstico apontou
como inalcançáveis por construção (`moda_masculina`, `saude_suplementacao`) voltaram com
`kept > 0`, e o teto de exposição de suplementos está mordendo corretamente (exatamente 5,
o `cycle_limit`). No ML, `moda_feminina` e `saude_suplementacao` continuam sem `category_hint`
de propósito (`trust_hint=False` nas URLs de categoria-pai) e caem no classifier por título.

### Achados novos surgidos no dry-run do B1 · 2026-08-19 · **não corrigidos**

**B7 — busca direcionada da Shopee 100% quebrada.** As 6 queries falharam com
`Shopee retornou erros GraphQL: [{'message': 'graphql: got null for non-null',
'extensions': {'code': 10010}}]` em `productOfferV2(keyword=...)`. É um bug **diferente**
do já conhecido `Unknown type "GenerateShortLinkInput"` (geração de link curto, achado em
2026-07-21) — este é o caminho de busca por palavra-chave. Degrada em silêncio operacional
(loga `ERROR` e segue), então a Shopee hoje coleta **só** por categoria. Somado ao B2, isso
significa que **a busca direcionada só funciona de fato na Amazon**.

**B8 — queries de `radar_category` sem sentido comercial.**
`search_query_planner._category_term` transforma a chave do radar em termo de busca
literal, gerando consultas como `faixa preco:ate 100` e `moda`. A primeira é lixo (busca
pelo nome do bucket, não por produto); a segunda é genérica demais para ter valor. As
queries de `radar_brand` (`nike tênis`, `lg oferta`) são as únicas com intenção comercial
real. Não mexido — é mudança de qualidade de curadoria, não do escopo da Onda 2.

### Verificação da Onda 2 · 2026-08-19

- `manage.py test apps.distribution apps.orchestration apps.scraping` → **110 testes, 1
  falha** (a mesma `test_publish_telegram_ai_curation` pré-existente já registrada acima).
  Onda 2 acrescentou 5 testes.
- `manage.py test` (suíte inteira) → **469 testes, 4 falhas**: a de telegram acima e mais 3
  em `test_link_builder_shopee` / `test_radar_mercado`. Todas **pré-existentes** —
  confirmado stashando `apps/` e `scrapers/` e reproduzindo em `HEAD` limpo. São testes que
  assumem feature desligada por default enquanto o `.env` real as tem ligadas
  (`SHOPEE_AFFILIATE_ENABLED`, radar de mercado); não têm relação com esta onda.

### Estado do repositório

Nada foi commitado: Ondas 1 e 2 estão no working tree (`git status`). Sem `git push`,
conforme o plano.
