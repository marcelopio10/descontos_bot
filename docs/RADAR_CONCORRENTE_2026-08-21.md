# Radar de concorrente — o observer como fonte de coleta (2026-08-21)

> Origem: o dono reportou que o volume voltou, mas os envios seguem repetitivos e
> que ofertas boas aparecem em outros grupos e não chegam ao nosso. Os exemplos
> que ele trouxe eram todos Mercado Livre com cupom: chinelo Reserva por R$57,
> Galaxy Watch 8, G-Shock, cuecas Calvin Klein, Fila Fastpace, whey Growth,
> Olympikus Veloz.

---

## Diagnóstico

### O que ele viu já estava no nosso banco — só não na nossa coleta

Ocorrências na janela de 7 dias:

| termo | mensagens observadas | ofertas que **nós** coletamos |
|---|---|---|
| reserva | 135 | 10 |
| chinelo | 88 | **0** |
| calvin klein | 78 | 1 |
| growth | 76 | **0** |
| olympikus | 64 | 6 |
| g-shock | 11 | **0** |
| galaxy watch | 10 | **0** |

O observer captura 4.388 mensagens de Mercado Livre por semana em 14 grupos.
Nossa coleta inteira, nos 3 marketplaces, rende 419 ofertas por semana. Densidade
de marca reconhecida: **37% nas mensagens deles, 24% nos nossos envios**.

A causa é o achado B2 (2026-08-18): a busca direcionada por texto no ML está
bloqueada pelo Akamai, então o ML entra só pelas 8 URLs de
`/ofertas?category=MLB...`. O que cabe ali é commodity — nos envios do dia
apareceram fita dupla face, tampas plásticas, painel de LED e pula-pula.

**Nenhum gate de curadoria resolve isso: gate corta, não amplia.** O laudo de
diversidade do mesmo dia já anotava que, se o volume caísse mais que o previsto,
o gargalo seria coleta.

### O observer chegava com até 24h de atraso

`created_at` de todas as mensagens estava agrupado em 01:00 UTC — o
`market-intel.timer` das 22h BRT era o único momento em que o banco recebia algo.
O buffer do `evolution_adapter` é janela rolante de 24h com teto de 300 mensagens
por grupo (`observerBuffer.ts`), então além do atraso havia perda em grupo
movimentado. Na primeira execução manual da ingestão, 711 mensagens entraram de
uma vez — todas represadas no buffer.

---

## Verificação técnica feita antes de projetar

Tudo abaixo foi conferido ao vivo, com a sessão impersonada do próprio scraper:

| Alvo | Resultado |
|---|---|
| `meli.la/<hash>` | **200**, redireciona para `www.mercadolivre.com.br/social/<vitrine>` |
| Página `/social/...` | **200**, 270-365KB, com `.poly-card` — os mesmos cards das páginas de categoria |
| `produto.mercadolivre.com.br/MLB-...-_JM` | 200 com 9,7KB e zero conteúdo (micro-landing) |
| `www.mercadolivre.com.br/p/MLB...` | redireciona para `/gz/account-verification` |

Ou seja: a página do anúncio continua bloqueada, mas a **vitrine de afiliado do
concorrente não está**. E como ela usa `.poly-card`, o `_parse_item` que já existe
funciona sem adaptação — o que garante que o `external_id` extraído aqui é o
mesmo da coleta por categoria (identidade consistente, requisito do dedup por
`produto_canonico_id`).

Duas armadilhas encontradas na verificação:

1. **O ID não pode sair do `og:image`.** O nome do arquivo carrega o ID do
   *asset*, não o do anúncio: no mesmo card, imagem `MLB78955357177` e href
   `MLB-3656481579`. Em alguns casos o asset é até de outro site (`MLA...`).
   O ID sai do href.
2. **O alvo nem sempre é o primeiro card**, e o `og:image` nem sempre casa. A
   seleção é pelo `og:title` — e **só** por ele (ver "Correção do chute", abaixo).

---

## O que foi implementado

| Camada | Arquivo | Papel |
|---|---|---|
| Scraper | `scrapers/mercado_livre.py::scrape_social_card` | Abre o link curto, acha o card do `og:title`, reusa `_parse_item` |
| Persistência | `apps/market_intel/models.py::ObservedOfferLink` | Uma linha por link resolvido: anúncio, preço, falha auditável |
| Serviço | `apps/market_intel/services/competitor_radar.py` | Seleção de candidatos, resolução, payloads e relatório |
| Comando | `resolve_competitor_links` | `--limit`, `--lookback-hours`, `--dry-run`, `--report`, `--json` |
| Coleta | `apps/scraping/services/adapters.py` | Terceiro ramo da união, atrás de `competitor_radar_enabled` |
| Proveniência | `search_provenance.py` | Novo `source_kind='competitor_radar'` |
| Agendamento | `scripts/radar-concorrente.{service,timer}` | Ingestão + resolução a cada 20 min |
| Parser | `apps/market_intel/services/parser.py` | Cupom em negrito do WhatsApp (`Cupom: *COMPENSAML*`) deixou de se perder |

Decisões que valem registro:

- **Resolução e coleta são passos separados.** O comando resolve no timer dele;
  `collect()` só lê o que já está resolvido, sem rede. Isso mantém a janela de
  coleta curta e deixa a resolução rodar mais vezes que o ciclo do bot.
- **Frescor de preço.** Só entra no pool o que foi resolvido nas últimas 6h — o
  preço vem do card no momento da resolução, e publicar preço velho é pior do que
  não publicar.
- **Nossos próprios grupos são excluídos** lendo `SocialChannel.target`, não por
  lista fixa: o canal de saída também é grupo observado, e sem isso o sistema
  republicaria a si mesmo.
- **Regras de categoria valem para o radar.** Os payloads não têm
  `category_hint` (não vieram de URL de categoria), então as regras são aplicadas
  localmente, com a categoria inferida do título, mais um piso próprio para o que
  o classifier devolve como `outros` — sem ele passaria monitor de R$1.756 num
  canal cujo teto de tecnologia é R$700.
- **Privacidade.** Nada que identifique grupo ou remetente entra no payload da
  oferta; a proveniência é só o rótulo `competitor_radar`.

### Settings (`apps.panel.models.Setting`, sem migração)

| Chave | Default | Efeito |
|---|---|---|
| `competitor_radar_enabled` | `false` | Liga o consumo do radar pela coleta |
| `competitor_radar_lookback_hours` | `12` | Janela de mensagens candidatas |
| `competitor_radar_max_resolutions` | `40` | Teto de links por execução |
| `competitor_radar_payload_freshness_hours` | `6` | Idade máxima do preço resolvido |
| `competitor_radar_max_payloads` | `30` | Teto de ofertas por ciclo de coleta |
| `competitor_radar_excluded_groups` | `[]` | Grupos extras a ignorar |
| `competitor_radar_fallback_min_discount` | `20` | Piso para título sem categoria |
| `competitor_radar_fallback_max_price` | `700` | Teto para título sem categoria |

Rollback: `competitor_radar_enabled=false` desliga o consumo sem parar a medição;
`systemctl --user disable --now radar-concorrente.timer` para tudo.

---

## Verificação

```bash
python3 manage.py test apps.market_intel apps.scraping apps.curation   # OK
python3 manage.py check && python3 manage.py makemigrations --dry-run --check
python3 manage.py resolve_competitor_links --report --lookback-hours 24
```

Execução real em 2026-08-21, 32 links resolvidos, **32/32 sem falha**:

| Métrica (24h) | Valor |
|---|---|
| Mensagens ML observadas | 634 |
| Com cupom | 461 |
| Links resolvidos | 32 |
| Anúncios distintos | 28 |
| Já no nosso pool | 11 |
| **Inéditos para nós** | **17** |

O radar entregaria 23 payloads (5 barrados pelas regras de categoria: 2 por preço,
3 por desconto). Entre os inéditos: Nike Court Lite 4, Nike SB Force 58, **Fila
Fastpace** (um dos exemplos do dono), Tênis Reserva R-ollie, Kit 2 Cuecas Calvin
Klein, Camiseta Puma, Camiseta Insider, Chinelo Rider.

Atribuição conferida ponta a ponta: o link publicado resolve com
`matt_word=mpio11` (nossa tag); o do concorrente, com `matt_word=dudu`.

---

## Segunda rodada — consenso entre grupos (mesmo dia)

> Origem: o dono observou que **todos os grupos anunciaram Insider no mesmo dia** e
> que nunca capturamos essa marca.

Três problemas encadeados, todos confirmados no banco:

> As duas primeiras correções abaixo entraram e continuam valendo para o campo
> `marca` (relatório de market intel), mas **deixaram de ser load-bearing para o
> radar**: a chave de consenso não depende mais de marca. Ver "3. A fila era
> ordenada por recência".

### 1. `insider` não existia no vocabulário de marcas

`BRAND_PATTERNS` tinha 25 marcas, só calçado esportivo e eletrônico. As 10
mensagens de Insider do dia saíram com `marca` **vazia** — o sinal existia e era
invisível. A lista foi ampliada para as marcas que de fato dominam os grupos
(vestuário, relógio, suplemento, beleza).

### 2. O casamento de marca era por substring

`if brand in normalized` fazia `'lg'` casar dentro de **"algodão"**. Havia 297
mensagens marcadas como marca `lg` em 7 dias, boa parte camiseta de algodão. O
campo alimenta o relatório de market intel e agora a fila do radar, então o ruído
se propagava. Passou a casar por palavra inteira, da marca mais específica para a
menos. Depois da correção, `marca=lg` em 24h caiu para 6 — todas TV e monitor.

### 3. A fila era ordenada por recência, o que equivale a sortear

A janela de 12h tem ~330 candidatos e a capacidade é de 20 por execução, 60 por
hora. Ordenar por chegada faz a oferta que 6 grupos estão empurrando esperar
atrás de 300 mensagens avulsas.

A fila passou a ordenar por **número de grupos distintos anunciando a mesma
oferta**, com uma chave de similaridade que **só ordena**: nunca descarta nem
funde, seguindo a mesma separação de identidade e similaridade firmada na
curadoria.

A primeira versão da chave foi `(marca, faixa de R$5)`, e ela tinha o mesmo vício
do problema que resolvia: dependia de `BRAND_PATTERNS`, lista escrita à mão.
Medido na janela de 12h, **66% das mensagens não tinham marca reconhecida** e
ficavam fora do ranking — e o consenso quebrava quando um grupo escrevia a marca
e o outro não, jogando dois grupos da mesma oferta em clusters diferentes.

A chave final é `(família de produto, faixa de R$5)`:

- **Família** vem de `product_family_key`, a mesma heurística dos gates de
  diversidade, com fallback por palavra-cabeça — cobre a cauda longa e a oferta
  sem marca nenhuma. Para extraí-la, `product_line` acha o nome do produto no
  meio da mensagem: descarta manchete, preço, cupom e CTA, prefere a linha em
  negrito e, sem negrito, a mais longa. Em mensagem de uma linha só (emoji +
  link + produto + preço + cupom, formato comum), a URL e o preço são recortados
  e a linha é truncada no primeiro marcador de cupom/CTA, em vez de descartada.
- **Faixa de R$5** porque o mesmo produto sai a R$56,00 num grupo e R$56,58 em
  outro.

| chave | cobertura da janela | clusters com 2+ grupos |
|---|---|---|
| `(marca, preço)` | 33% | 18 |
| `(família, preço)` | **99%** | **50** |

Nas 60 primeiras posições da fila, nenhuma fica sem chave (antes, 60% eram
mensagens sem marca, ranqueadas só por recência). O topo real passou a ser
dominado por marcas que não estão em lista nenhuma — Mash, Sandrini, Paris
Elysees, Aramis, Dark Lab —, que é exatamente o que se queria: consenso é
propriedade da oferta, não da marca.

Junto entrou a singularização do fallback de `product_family_key`: 'cuecas' e
'cueca' eram famílias diferentes, o que dividia consenso no radar e enfraquecia o
espaçamento na publicação.

### Intercalação por cluster

Consenso alto significa, por construção, várias mensagens equivalentes: as 4
primeiras posições eram 4 cópias da mesma camiseta e consumiam 4 requisições para
trazer um produto só. A fila é **intercalada** (`_interleave_by_cluster`): uma
oferta de cada por rodada. As repetições não são descartadas, vão para as rodadas
seguintes — cada link é resolvido no máximo uma vez na vida.

Topo real depois de tudo: Kit 10 Cuecas Mash (4 grupos), Kit 3 Camisetas Térmicas
(4), Kit 15 Pares Meias Sandrini (4), Body Splash Árabe (3), Perfume Paris
Elysees (3), Shorts Esportivo (3), Sapato Loafer (3), Camiseta Dark Lab (3).

### Correção do chute no card em destaque

A primeira versão, sem casamento de título, usava o card em destaque da vitrine.
Isso **trocava o produto em silêncio**, e aconteceu duas vezes em 63 resoluções:

- mensagem de "micro-ondas consul 23l cms23ab" → gravou "Micro-ondas MTO30 20L";
- mensagem de "Insider **Light** T-Shirt" → gravou "Camiseta **Daily** T-shirt".

A oferta gravada era real e com preço correto, mas não era a que o grupo
anunciou — o que derruba a premissa do radar, que é publicar justamente a oferta
com consenso. Agora, sem casamento de `og:title`, não resolve: registra
`social_card_alvo_nao_identificado` e segue. O caso mais comum é o link apontar
para a raiz da vitrine, quando o `og:title` vira "Minhas recomendações".

Os dois registros afetados: o da Insider foi removido para nova tentativa sob a
regra estrita; o do micro-ondas permaneceu como oferta comum no pool (preço
correto, produto real, apenas não o anunciado).

## Medição contínua — aderência aos grupos

`python3 manage.py analyze_group_adherence --days 7 [--channel] [--json]`
(`apps/market_intel/services/adherence.py`), rodando também no
`market_intel_daily.sh` para virar série temporal no log.

Existe porque o relatório de market intel media cobertura do **catálogo**, não do
que foi **enviado**. As perguntas são outras três: do que publicamos, quanto eles
também publicaram; do que eles empurram com força, quanto chegou ao canal; e com
quanto atraso.

O casamento usa a chave de similaridade do radar (família + faixa de R$5) em vez
de sobreposição de tokens: o texto do grupo é copy de marketing ("60 CONTO NA
PEITA DA UNDER"), não título de anúncio, e os dois quase nunca compartilham
tokens suficientes.

**Duas taxas, de propósito.** O critério estrito (família + faixa de preço)
subestima de forma sistemática, porque eles anunciam o preço com cupom e nós o de
página — a mesma camiseta cai em faixas diferentes. O critério por família
superestima, porque duas camisetas quaisquer casam. Reportar um número só seria
enganoso.

Não há métrica de diferença de preço aqui: dentro de uma família cabem um tênis
de R$99 e um de R$359, então a comparação mediria variedade de catálogo, não
desvantagem de preço. O efeito do cupom está medido acima, onde o par é o mesmo
anúncio.

### Primeira leitura (2026-08-21, `whatsapp_principal`, 7 dias)

| Métrica | Valor |
|---|---|
| Envios | 254 |
| Eco nos grupos | 21,7% estrito / 61,4% por tipo de produto |
| Ofertas com 3+ grupos | 341 |
| Dessas, publicadas | 33 (**9,7%**) |

Por origem da coleta, que é onde a leitura fica clara:

| Origem | Envios | Eco |
|---|---|---|
| `generic_fallback` (`/ofertas` + daily deals) | 202 | 17,8% |
| `radar_category` | 17 | 5,9% |
| `radar_brand` (busca direcionada, só Amazon) | 14 | 50,0% |
| `competitor_radar` | 14 | **78,6%** |
| `radar_price_band` | 7 | 0,0% |

**Latência do radar**, medida no par exato (mensagem → `ObservedOfferLink` →
`Delivery`, mesmo produto por construção): **mediana de 1,9h** entre a mensagem
do grupo e o nosso envio, mínimo 0,7h e máximo 5,9h — 0,4h até resolver o link.
Contra ~53h do caminho genérico.

> O "atraso" da tabela por origem é outra coisa e satura: compara com a mensagem
> mais antiga da janela de 72h, e o radar mira justamente campanha longa. Para
> latência, vale o número do par exato.

**As maiores lacunas** são o que 6 a 8 grupos publicaram e nós, zero: camiseta
Insider ~R$55, calça jeans wide leg ~R$45, kit creatina ~R$55, camiseta Malwee
~R$40, mochila tática ~R$75, tênis Puma Flyer Lite ~R$180, tênis Mizuno Oracle
~R$235, perfume Paris Elysees ~R$65.

**O que só nós publicamos** tem cara reconhecível: cartão de memória, boneco
Sonic, escavadeira de controle remoto, cartas Pokémon, blocos magnéticos, jogo de
lençol. É o pool de commodity do `/ofertas` — 199 dos 254 envios.

## Limitação que a fase 2 não resolve: o preço é do cupom

Dos 32 links resolvidos, **22 têm cupom na mensagem e anunciam preço abaixo do
preço de página, em média 22% abaixo**:

| Página | Anunciado por eles | Cupom | Produto |
|---|---|---|---|
| R$269 | R$212 | COMPENSAML | Tênis Fila Fastpace |
| R$122 | R$100 | COMPENSAML | Kit 6 Cuecas Lupo |
| R$96 | R$79 | COMPENSAML | Kit 2 Cuecas Calvin Klein |
| R$67 | R$55,60 | COMPENSAML | Kit 2 Camisa Polo Piquet |

A fase 2 nos dá **o produto**; não dá **o preço deles**. Publicaríamos o Fila a
R$269 enquanto o grupo ao lado publica R$212. Fechar essa diferença é a fase 3:
campo de cupom na oferta e preço final com cupom no caption.

Enquanto ela não existe, o piso de desconto do próprio `_parse_item`
(`MIN_DISCOUNT = 5`) descarta a oferta cujo valor só existe com cupom — o que é o
comportamento honesto para o formato de caption atual, que anuncia "De X por Y".
O contador `no_discount` do comando mede quanto se perde por aí.

## Outras limitações conhecidas

- **Só Mercado Livre.** Amazon (`amzn.to`) e Shopee (`s.shopee.com.br`) aparecem
  no observer, mas não têm caminho de resolução verificado. `SUPPORTED_MARKETPLACES`
  é explícito para não fingir cobertura que não existe.
- **Chegamos depois.** A oferta é descoberta porque outro grupo publicou; no
  melhor caso saímos ~20 min atrás deles.
- **Vitrine sem casamento de título não resolve.** Custa cobertura (o link é
  descartado), mas é o preço de não trocar o produto anunciado por outro.
- **O consenso é medido por família e faixa de preço**, não por produto: dois
  modelos diferentes na mesma família e faixa contam como uma oferta só na hora
  de ordenar. Foi o caso da Insider Daily e Light, as duas a R$56. Só afeta ordem
  de fila, e a intercalação garante que o irmão saia na rodada seguinte.
- **`product_line` é heurística de formato.** Cobre 99% das mensagens da janela
  medida, mas grupo que mude o padrão de copy pode cair fora — o efeito é perder
  o consenso daquela mensagem, não perder a mensagem.
- **Depende do `ML_COOKIE`** para gerar o link de afiliado, como todo o resto da
  coleta do ML. Cookie vencido derruba o radar junto.

---

## Estado

Implementado e medindo. **Não publica ainda**, por dois motivos somados:

1. `competitor_radar_enabled` está `false`.
2. O `run-bot.service` em produção subiu em 2026-08-20 10:36 e roda o código
   anterior tanto ao radar quanto aos gates de diversidade do mesmo dia. A coleta
   só acontece dentro do `run_bot` — nenhum timer faz scraping —, então a fase 2
   fica inerte até o serviço reiniciar.
