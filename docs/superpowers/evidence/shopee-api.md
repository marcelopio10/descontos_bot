# Evidência — Shopee Affiliate Open API

- Data/hora da validação: 2026-08-07
- Endpoint: `https://open-api.affiliate.shopee.com.br/graphql`
- Fonte oficial: Shopee Affiliate Open API Explorer V2
- Autenticação: chamada assinada pelo cliente existente retornou schema válido; não houve erro de credencial.

## Resultado real

Introspection autenticada retornou operações:

- `conversionReport`
- `partnerOrderReport`
- `validatedReport`
- `productOfferV2`
- `shopOfferV2`
- `generateShortLink`
- `generateBatchShortLink`

`conversionReport` aceita filtros por:

- `purchaseTimeStart` / `purchaseTimeEnd`
- `completeTimeStart` / `completeTimeEnd`
- status de conversão/pedido
- produto, pedido e loja
- paginação por `limit` e `scrollId`

Schema real de `ConversionReport` expõe:

- `clickTime`
- `purchaseTime`
- `conversionId`
- `conversionStatus`
- `grossCommission`
- `estimatedTotalCommission`
- `totalCommission`
- `netCommission`
- `utmContent`
- `referrer`
- `orders`

Itens do pedido expõem:

- `orderId`
- `orderStatus`
- `shopId`
- `itemId`
- `itemName`
- `itemPrice`
- `actualAmount`
- `refundAmount`
- `qty`
- `itemCommission`
- `itemTotalCommission`
- `attributionType`
- `channelType`

Consulta real de janela de sete dias, limite um, retornou:

- `conversion_report_api=True`
- `nodes=1`
- `pageInfo.hasNextPage=True`
- `pageInfo.scrollId` presente

Nenhuma linha de pedido ou valor financeiro foi reproduzida nesta evidência.

## Problema encontrado

Schema atual exige:

```graphql
mutation generateShortLink($input: ShortLinkInput!)
```

Código anterior usava:

```graphql
mutation generateShortLink($input: GenerateShortLinkInput!)
```

Patch aplicado no worktree de homologação:

- `apps/marketplaces/services/shopee_link_generator.py`
- `GenerateShortLinkInput` → `ShortLinkInput`

Introspection confirmou campos atuais de `ShortLinkInput`:

- `originUrl` obrigatório
- `subIds` opcional

Tentativa de geração com URL fictícia e SubIDs de teste foi recusada pela API com `invalid sub id`; isso confirma que a operação chegou à validação de negócio. Não foi usado link de produção nem oferta publicada.

## Testes

Passou:

```text
apps.marketplaces.tests.test_shopee_link_generator
Ran 4 tests — OK
```

Suíte combinada de link builder apresentou 1 falha e 1 erro preexistentes relacionados a mocks/`resolve_affiliate_link`, fora do patch do schema. Não foram corrigidos nesta fase.

## Status da fase

`HOMOLOGADO_API` para acesso e consulta de conversões/comissões Shopee.

`PENDENTE` para:

- corrigir e testar geração de short link com URL de produto válido;
- adaptar resposta GraphQL ao parser/`AffiliateConversion`;
- validar associação de `itemId`, `shopId`, SubIDs e canal;
- validar paginação completa e status cancelado/ajustado;
- confirmar limites, atraso e permissões da conta.
