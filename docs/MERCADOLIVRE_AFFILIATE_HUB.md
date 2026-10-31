# Hub de afiliados do Mercado Livre como fonte de coleta

Status: implementado e validado sem gravação; **desligado em produção** até aprovação do operador.

## O que é

O portal de afiliados (`/afiliados/hub`) tem a lista "Selecionados para você", com filtros por categoria, comissão extra e mais vendidos. O portal busca esses produtos pela rota interna:

```text
POST https://www.mercadolivre.com.br/affiliate-program/api/hub/search?is_affiliate=true&device=desktop
{"search": "", "filters": [{"id": "category", "value": "MLB1051"}], "sort": "relevance", "offset": 0}
```

Cada card traz ID do anúncio/produto, URL, preço atual e anterior, % OFF, nota, selo ("MAIS VENDIDO") e, quando há, a comissão extra ("GANHOS EXTRAS N%"). Não traz vendedor nem reputação.

A rota é interna e não documentada: o Mercado Livre pode alterá-la sem aviso. Ela usa a mesma sessão `ML_COOKIE` do scraper e do motor afiliado.

## Como entra na coleta

Quarto ramo de `ScraperAdapter.collect()` (`apps/scraping/services/adapters.py`), depois de categorias e antes do radar de concorrente:

1. Para cada URL de `scrapers/category_targets.py` com `category=MLB...`, busca a primeira página por relevância e a primeira página com comissão extra (16 chamadas por ciclo, com 2,0–4,5 s entre elas).
2. `MercadoLivreScraper.scrape_affiliate_hub()` aplica desconto mínimo e teto de preço da categoria **antes** de gerar o link afiliado.
3. Os payloads seguem o caminho normal: dedup, `_apply_category_filters` (inclui `cycle_limit`), normalização, curadoria e gates de distribuição.

Identidade e URL:

| Tipo de card | URL usada | Identidade |
|---|---|---|
| `product` | `https://www.mercadolivre.com.br/<slug>/p/MLB...` | ID do produto de catálogo, igual ao scraper |
| `item` | `https://produto.mercadolivre.com.br/MLB-...` | ID do anúncio |
| `user_product` | `https://produto.mercadolivre.com.br/MLB-<metadata.id>` | ID do anúncio (`/up/MLBU...` não tem identidade aceita) |

Sinais gravados no `raw_payload` da oferta: `affiliate_hub.card_type`, `extra_commission`, `commission_pct`, `highlight`; `search_provenance.source_kind = affiliate_hub`; `Offer.collection_source = affiliate_hub`.

## Falhas

- HTTP 401/403 ou redirecionamento: interrompe o hub no ciclo, registra `ml_affiliate_hub_sessao_recusada` e aciona o alerta existente `ml_cookie_expirado`.
- 429, resposta não JSON ou formato inesperado: interrompe o hub no ciclo. Outros status: pula só aquela busca.
- Falha do hub não derruba o restante da coleta do Mercado Livre.
- Flag ilegível no banco mantém o hub desligado.

## Ligar, ajustar e desligar

As flags ficam em `Setting` e são lidas a cada ciclo; não exigem reinício do `run-bot.service` depois que o código novo estiver carregado.

```bash
# ligar
.venv/bin/python3 manage.py shell -c "from apps.panel.models import Setting; Setting.objects.update_or_create(key='affiliate_hub_enabled', defaults={'value': '1', 'description': 'Coleta do hub de afiliados do ML'})"

# só relevância, sem a página de comissão extra (8 chamadas por ciclo)
.venv/bin/python3 manage.py shell -c "from apps.panel.models import Setting; Setting.objects.update_or_create(key='affiliate_hub_extra_commission_enabled', defaults={'value': '0', 'description': 'Página extra de comissão do hub'})"

# desligar (rollback)
.venv/bin/python3 manage.py shell -c "from apps.panel.models import Setting; Setting.objects.update_or_create(key='affiliate_hub_enabled', defaults={'value': '0', 'description': 'Coleta do hub de afiliados do ML'})"
```

O código novo só passa a rodar no serviço após reinício autorizado do `run-bot.service`. Com a flag em `0` (padrão), o comportamento é idêntico ao anterior.

## Acompanhamento

```bash
grep -E 'ml_affiliate_hub|collect_summary marketplace=mercadolivre' logs/bot.log | tail
```

```sql
select collection_source, count(*) from offers_offer
where marketplace_id = 1 and last_seen_at >= datetime('now', '-24 hours') group by 1;
```

## Limitações conhecidas

- O link `/p/` do catálogo cai na oferta vencedora do produto. Se o vendedor recomendado pelo hub não for o vencedor, preço e comissão extra podem diferir do card.
- Sem reputação do vendedor no card. A checagem por `/users/bulk` da API oficial depende do token OAuth, que ainda não tem rotação persistida.
- A curadoria ainda não usa `commission_pct` nem `highlight` para priorizar; os sinais ficam gravados para essa etapa.
