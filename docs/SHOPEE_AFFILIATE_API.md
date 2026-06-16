# Conector Shopee Affiliate Open API — Sprint 7B

MVP seguro do conector oficial GraphQL da Shopee. Coleta ofertas elegíveis,
normaliza para `Offer`, gera links rastreáveis e aplica disclosure publicitário.
**Não publica automaticamente** e fica travado até validação real.

## Componentes

| Arquivo | Responsabilidade |
|---|---|
| `apps/marketplaces/services/shopee_affiliate_client.py` | Assinatura SHA256, header de auth, retry/backoff, erros |
| `apps/marketplaces/services/shopee_collectors.py` | `ProductOfferCollector` via `productOfferV2` |
| `apps/marketplaces/services/shopee_normalizer.py` | Item Shopee → `Offer` (dedupe por `itemId+shopId`) |
| `apps/marketplaces/services/shopee_link_generator.py` | subIds por canal; `offerLink` ou `generateShortLink` |
| `apps/marketplaces/management/commands/collect_shopee_offers.py` | Coleta dry-run/save |
| `apps/curation/services/ad_disclosure.py` | `#publicidade` obrigatório + bloqueio de clickbait |

## Autenticação

```
Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sig}
sig = SHA256(AppId + Timestamp + Payload + Secret)
```

`Payload` é exatamente o corpo JSON enviado (serialização determinística com
`sort_keys`). O secret nunca aparece em log nem no header além da assinatura.

## Gates de segurança

- `SHOPEE_AFFILIATE_ENABLED=false` (default): `--save` aborta; `--dry-run` e testes seguem.
- `--dry-run` é o default do comando; `--save` é obrigatório para persistir.
- Marketplace `shopee` precisa existir (`seed_marketplaces`).
- Toda publicação Shopee carrega `#publicidade`; link publicado é sempre afiliado/tracked.

## Operação (validação 7B com credenciais reais)

```bash
# 1. credenciais no .env local (nunca no Git)
#    SHOPEE_AFFILIATE_APP_ID=...  SHOPEE_AFFILIATE_SECRET=...

# 2. marketplace
python3 manage.py seed_marketplaces

# 3. dry-run — valida schema/assinatura sem gravar
python3 manage.py collect_shopee_offers --keyword "fone bluetooth" --limit 5 --dry-run

# 4. persistir lote pequeno (exige SHOPEE_AFFILIATE_ENABLED=true)
python3 manage.py collect_shopee_offers --keyword "fone bluetooth" --limit 5 --save

# 5. curadoria/publicação travada em homolog/dry-run
python3 manage.py publish_offers --dry-run
python3 manage.py publish_telegram --dry-run --once --channel telegram_homolog
```

O comando loga `recebidas / normalizadas / criadas / atualizadas / rejeitadas`.

## Normalização

- `external_id = '{itemId}:{shopId}'`; `offer_hash` independe da URL (dedupe estável).
- `current_price = priceMin or price`; `discount_pct = priceDiscountRate`.
- `original_price` derivado só com desconto confiável (0 < rate < 100); senão nulo.
- `affiliate_url = offerLink` quando válido; item bruto preservado em `raw_payload`.

## Pendente (Sprint 7C — após homologação)

- `conversionReport` → `AffiliateConversion` (fonte de verdade de mensuração).
- Shopee no dashboard privado.
- Datafeeds FULL/DELTA (`listItemFeeds`/`getItemFeedData`).

## Schema

A query `productOfferV2` em `shopee_collectors.py` é a hipótese inicial; a
primeira execução real com credenciais valida os campos exatos da conta. Ajustar
o normalizer se o schema divergir antes de persistir em escala.
