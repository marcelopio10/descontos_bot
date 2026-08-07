# Relatório de Homologação de APIs de Afiliados

Data: 2026-08-07
Branch: `homologacao-tecnica-apis`

## Decisão arquitetural

Links de Mercado Livre e Shopee permanecem diretos. Não há redirect próprio. Atribuição depende de mecanismo nativo do marketplace e ingestão de fonte oficial.

## Shopee — `HOMOLOGADO_API` parcial

Fontes oficiais:

- https://open-api.affiliate.shopee.com.br/explorer
- https://open-api.affiliate.shopee.com.br/explorer/v2
- https://open.shopee.com/developer-guide/702

Evidência real:

- endpoint brasileiro respondeu com credenciais configuradas no projeto;
- introspection autenticada retornou `conversionReport`, `partnerOrderReport`, `validatedReport`, `productOfferV2`, `generateShortLink` e `generateBatchShortLink`;
- `conversionReport` retornou registros reais em janela de sete dias;
- resposta expõe conversão, pedido, item, preço, reembolso, comissão, status e paginação;
- adapter read-only executado em produção de dados: 2 nós, 4 linhas normalizadas, paginação presente;
- nenhuma persistência, publicação ou alteração de oferta executada.

Campos confirmados:

- conversão: `conversionId`, `conversionStatus`, `clickTime`, `purchaseTime`;
- comissão: `grossCommission`, `estimatedTotalCommission`, `totalCommission`, `netCommission`;
- produto: `itemId`, `shopId`, `itemName`, `itemPrice`, `actualAmount`, `qty`;
- pedido: `orderId`, `orderStatus`;
- atribuição disponível no schema: `attributionType`, `channelType`, `utmContent`, `referrer`.

Limitação importante:

- SubIDs nativos não apareceram no schema consultado;
- `utmContent`, `referrer` e `channelType` não serão tratados como SubID;
- `social_channel` permanece `None` até existir evidência explícita;
- comissão/produto podem ser reconciliados por item, mas canal ainda não.

Correção aplicada:

- schema atual exige `ShortLinkInput`;
- código usava `GenerateShortLinkInput`;
- alteração aplicada em `apps/marketplaces/services/shopee_link_generator.py`;
- testes específicos: 6 passaram;
- geração de short link com URL fictícia foi recusada por `invalid sub id`, após atingir validação de negócio.

Arquivos:

- `apps/marketplaces/services/shopee_conversion_api.py`
- `apps/marketplaces/tests/test_shopee_conversion_api.py`
- `docs/superpowers/evidence/shopee-api.md`

## Amazon — `BLOQUEADO_CREDENCIAL_PERMISSAO`

Fontes oficiais:

- https://associados.amazon.com.br/creatorsapi/docs/en-us/introduction
- https://associados.amazon.com.br/creatorsapi/docs/en-us/onboarding
- https://associados.amazon.com.br/creatorsapi/docs/en-us/api-reference
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/get-started/using-sdk
- https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation

Pesquisa:

- Creators API disponível para Amazon.com.br;
- registro da aplicação é requisito;
- documentação global registra Reporting API com geração/gerenciamento de relatórios S3 a partir do SDK 1.1.0;
- documentação brasileira consultada confirma Creators API, mas não comprovou habilitação da Reporting API para esta conta.

Estado local:

- tag de Associado presente;
- credenciais Creators API ausentes;
- nenhuma chamada autenticada de Reporting API possível.

Bloqueio externo:

- registrar/habilitar Creators API no Associates Central;
- obter credenciais por mecanismo oficial;
- confirmar Reporting API para locale Amazon.com.br.

Não foi feita automação de login nem scraping do painel.

## Mercado Livre — `BLOQUEADO_SEM_FONTE_OFICIAL`

Fontes oficiais:

- https://developers.mercadolivre.com.br/pt_br/api-docs-pt-br
- https://www.mercadolivre.com.br/ajuda/metricas-programa-afiliados_32755
- https://www.mercadolivre.com.br/knowledge-hub/32755
- https://www.mercadolivre.com.br/l/afiliados-entenda-suas-metricas

Pesquisa:

- APIs gerais disponíveis para catálogo, seller, anúncios e pedidos;
- essas APIs não comprovam conversão/comissão de afiliado;
- documentação de afiliados aponta para painel de métricas atualizado aproximadamente a cada 24 horas, com janela de até 180 dias;
- não foi localizada API pública documentada para conversões, vendas atribuídas ou comissões de afiliado;
- não foi localizada exportação oficial programática pública.

Limite externo:

- somente suporte/programa do Mercado Livre pode confirmar eventual acesso privado, API de parceiro ou relatório automatizável específico da conta.

Não foi usado scraping, captura XHR, Playwright ou redirect próprio.

## Verificação

```text
manage.py check: OK
Shopee adapter + short-link tests: 6 OK
live Shopee adapter: PASS
```

## Estado do P0

```text
Shopee: API de conversão/comissão homologada por item; canal ainda não comprovado.
Amazon: bloqueada até registro/habilitação externa da Creators API.
Mercado Livre: sem fonte oficial automatizável pública encontrada.
P0 universal: não resolvido.
```

Receita sem fonte oficial automatizada permanece `unknown`; não usar estimativa como comissão confirmada.
