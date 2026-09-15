# Integração do Mercado Livre pela API pública

Status da implementação: código local implementado; validação externa depende de OAuth autorizado.

## Fluxos

Fluxo legado, disponível para rollback:

```text
MercadoLivreScraper -> HTML de ofertas/categorias -> normalização -> Offer
```

Fluxo padrão da API:

```text
/sites/MLB/search
  -> /items/bulk?ids=... (lotes de 20)
  -> /items/{id}/sale_price?context=channel_marketplace
  -> /users/{seller_id}?attributes=seller_reputation
  -> ProductNormalizer
  -> OfferEligibilityPolicy
  -> OfferRepository salva product_url
  -> ExistingAffiliateLinkEngineAdapter recebe product_url
  -> affiliate_url é salvo separadamente
```

O caminho de busca API não usa `ML_COOKIE`, `ML_CSRF_TOKEN`, browser, BeautifulSoup ou URLs HTML. Depois da persistência, o motor afiliado legado ainda pode usar `ML_COOKIE`, `ML_CSRF_TOKEN` e `ML_AFFILIATE_TAG` para gerar `affiliate_url`; essa dependência é separada, preservada e não é usada para buscar produtos. O endpoint privado legado não foi substituído nem copiado para a busca.

## Endpoints usados

- `GET /sites/MLB/search`: `q`, `category`, `offset`, `limit` e `sort` somente quando confirmado/documentado.
- `GET /items/bulk?ids=ID1,ID2`: multiget oficial recomendado, máximo de 20 por lote; resposta usa `status_code`, `id` na raiz e `body`.
- `GET /items/{ITEM_ID}`: detalhe individual quando necessário.
- `GET /items/{ITEM_ID}/sale_price?context=channel_marketplace`: preço contextual, `amount`, `regular_amount`, `currency_id` e `reference_date`.
- `GET /users/{USER_ID}?attributes=seller_reputation`: reputação do vendedor.

`/items?ids=...` está em processo de descontinuação. O fluxo usa `/items/bulk?ids=...`, conforme a documentação atual; não depende do endpoint antigo.
Na documentação atual, os endpoints antigo e novo coexistem até 25/10/2026; o
cliente já usa o novo contrato (`status_code`, `id` na raiz e `body`) desde a
implementação inicial. `available_quantity` retornado pela API pública pode ser
uma faixa referencial, não o estoque exato; a política trata zero como
indisponível e não promete precisão maior que a fonte.

Fontes oficiais:

- https://developers.mercadolivre.com.br/pt_br/itens-e-buscas
- https://developers.mercadolivre.com.br/pt_br/api-de-precos
- https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao/rate-limit-erro-429
- https://developers.mercadolivre.com.br/pt_br/crie-uma-aplicacao-no-mercado-livre

## Autenticação e cadastro

1. Ter uma conta Mercado Livre ativa, preferencialmente a conta proprietária da solução.
2. Criar uma aplicação em “Minhas aplicações” no DevCenter brasileiro.
3. Configurar nome, descrição, Redirect URI HTTPS estático e escopo de leitura.
4. Usar OAuth 2.0 com usuário administrador, não operador/colaborador. PKCE é recomendado pela documentação.
5. Obter `Client ID`, `Client Secret`, `access_token` e `refresh_token`.
6. Guardar tudo somente no `.env` local/protegido. Nunca colocar token em fixture, log, banco ou Git.
7. Validar o acesso com `GET /users/me` ou o comando local abaixo sem imprimir o token.

A documentação retorna a validade do access token no campo `expires_in` e mantém refresh token com validade própria. O provider implementado faz no máximo um refresh em memória por requisição 401; persistência automática em `.env` só deve ser habilitada com writer local protegido e revisão própria.

As páginas atuais também informam que os campos `price`, `base_price` e `original_price` de `/items` serão descontinuados para consulta de preço; por isso o resolver consulta primeiro `/items/{ITEM_ID}/sale_price?context=channel_marketplace` e só usa os campos do item como fallback documentado.

## Variáveis

```env
ML_API_BASE_URL=https://api.mercadolibre.com
ML_API_SITE_ID=MLB
ML_API_ACCESS_TOKEN=
ML_API_CLIENT_ID=
ML_API_CLIENT_SECRET=
ML_API_REFRESH_TOKEN=
ML_API_REDIRECT_URI=
ML_API_TIMEOUT_SECONDS=15
ML_API_MAX_RETRIES=3
ML_API_PAGE_SIZE=50
ML_API_CONTEXT=channel_marketplace
ML_API_CONTEXTUAL_PRICE_ENABLED=true
ML_API_ITEM_CACHE_TTL_SECONDS=900
ML_API_SELLER_CACHE_TTL_SECONDS=86400
ML_API_ALLOWED_SELLER_LEVEL_IDS=
MERCADOLIVRE_API_SEARCH_ENABLED=false
```

`ML_API_ALLOWED_SELLER_LEVEL_IDS` deve ser preenchido somente depois de observar um valor real aprovado de `seller_reputation.level_id`. Vazio é fail-closed. A API só é selecionada quando `MERCADOLIVRE_API_SEARCH_ENABLED=true` estiver explícita no ambiente; a ausência da variável mantém o scraper legado. O rollback por Setting permanece disponível como kill switch adicional; reativação exige alteração operacional explícita.

## Erros e rate limit

- 400/404: não retryable; item/request inválido ou inexistente.
- 401: tenta refresh uma vez; sem refresh válido, falha fechada.
- 403: falha de permissão/auth; não degrada para scraper.
- 429: respeita `Retry-After`, depois usa backoff exponencial com jitter.
- 5xx e timeout: retry limitado com jitter.
- Logs registram endpoint sanitizado, status e tentativa; nunca corpo, Authorization, cookie ou segredo.

## Link original e idempotência

`Offer.product_url` é o permalink canônico. Se o permalink faltar, só é derivado `/p/MLB...` para id MLB validado; o comportamento deve ser confirmado no probe real.

O original é salvo e o `ScrapingItemResult` fica `pending` antes da chamada do motor afiliado. Se o processo cair, a próxima tentativa reutiliza o original persistido. O mesmo item é reconciliado por `marketplace + external_id`, inclusive quando a primeira captura usou URL derivada e a seguinte trouxe permalink completo.

O `affiliate_url` só é preenchido quando o motor atual retorna um link gerado. Fallback ao original fica auditado como `affiliate_failed`, e `Offer.affiliate_link` continua fornecendo `product_url`.

## Rollback

A Setting `mercadolivre_api_search_enabled` e o override `MERCADOLIVRE_API_SEARCH_ENABLED=0` selecionam o scraper legado. Não apagar `scrapers/mercado_livre.py`. Em homologação:

```bash
.venv/bin/python manage.py shell -c "from apps.panel.models import Setting; Setting.objects.update_or_create(key='mercadolivre_api_search_enabled', defaults={'value': '0', 'description': 'Rollback para scraper legado'}); print('rollback=legacy')"
```

O rollback não remove ofertas nem altera `affiliate_url` já persistido.

## Probe local

```bash
.venv/bin/python manage.py check_mercadolivre_api --limit 1
```

Sem token, o comando falha informando somente o nome da variável. Com token válido, imprime status/contagem, nunca o valor do token.

## Custos

As páginas oficiais consultadas não apresentam uma tarifa de conexão/API. Registrar como “nenhuma cobrança de API identificada nas fontes consultadas; confirmação de termos pendente”, sem prometer custo zero. Mensalidade de terceiros, custos de infraestrutura, taxas de venda ou regras do programa de afiliados são categorias separadas.

## Evidências

- Testes automatizados usam transportes falsos e fixtures determinísticas.
- Probe HTTP 200 com credencial é evidência externa separada e ainda depende de credencial autorizada.
- `ScrapingItemResult` diferencia `discarded`, `failed`, `affiliate_failed` e `accepted`.
