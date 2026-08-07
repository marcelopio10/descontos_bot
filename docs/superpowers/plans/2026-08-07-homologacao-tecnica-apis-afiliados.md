# Homologação Técnica das APIs de Afiliados — Plano de Implementação

> **Para agentes de execução:** usar `executing-plans` ou `subagent-driven-development` ao implementar este plano. Cada etapa possui critérios de evidência e não autoriza alteração de links ou envio em produção por si só.

**Objetivo:** determinar, com chamadas reais e fontes oficiais, quais marketplaces permitem consultar automaticamente conversões, vendas, comissões e atribuição por oferta/canal sem intermediar links nem fazer scraping manual dos portais.

**Arquitetura:** preservar links diretos dos marketplaces, usando somente SubID/Tracking ID nativo. Criar/adaptar conectores somente para fontes oficiais automatizáveis: API, relatório oficial disponibilizado por endpoint/S3/e-mail ou exportação autorizada. Quando não houver fonte oficial legível por máquina, registrar a receita como `unknown`, sem estimativa apresentada como venda.

**Stack:** Django/Python do `descontos.bot`, clientes GraphQL/REST existentes, parsers de relatórios em `apps/analytics/services/affiliate_parsers/`, banco Django, testes unitários e probes de integração controladas.

---

## Regras de segurança e escopo

- Não interpor domínio próprio nos links de Mercado Livre ou Shopee.
- Não reativar nem expandir `site/api/click.js`, `site/api/clicks.js` ou `ClickEvent` para medir ML/Shopee.
- Não usar Playwright/headless, captura de XHR ou scraping do portal como solução padrão.
- Não imprimir, salvar em relatório ou versionar tokens, secrets, cookies, headers de autorização ou respostas brutas que contenham dados pessoais.
- Usar somente chamadas de leitura durante a homologação. Não gerar link real, publicar oferta, alterar campanha ou alterar configuração de produção sem uma aprovação separada.
- Probes reais devem usar credenciais carregadas pelo ambiente existente e produzir apenas evidência redigida em `/tmp/descontos-api-homologacao-*`.
- Se um relatório oficial for baixado, preservar somente hash, esquema, contagens e campos necessários para teste; não versionar o arquivo bruto.

## Critérios de saída do plano

A homologação só estará concluída quando cada marketplace receber um dos estados abaixo:

- `HOMOLOGADO_API`: chamada oficial real retorna conversão/comissão e atribuição suficientes.
- `HOMOLOGADO_RELATORIO_AUTOMATICO`: fonte oficial automatizável retorna os mesmos dados, mesmo sem API transacional.
- `PARCIAL_CATALOGO_APENAS`: API acessível apenas para produto/preço; não serve para P0 de rentabilidade.
- `BLOQUEADO_SEM_FONTE_OFICIAL`: nenhum caminho automatizável oficial foi comprovado.
- `BLOQUEADO_CREDENCIAL_PERMISSAO`: existe documentação, mas a conta não possui acesso.

A decisão final deve conter, por marketplace:

- fonte oficial usada;
- método de autenticação;
- aprovação necessária;
- custo conhecido ou `não publicado`;
- limite/cadência;
- atraso dos dados;
- campos retornados;
- granularidade por produto/canal/campanha;
- forma de reconciliar com `Offer`, `Delivery` e `AffiliateConversion`;
- riscos de política e operação;
- evidência redigida com data, URL e status HTTP/operação.

---

## Fase 0: congelar o contrato e preparar a evidência

### Tarefa 0.1: registrar o estado atual sem mutação

**Arquivos:**
- Consultar: `docs/LINK_POLICY.md`
- Consultar: `docs/AFFILIATE_REPORTS_INGESTION.md`
- Consultar: `apps/analytics/services/link_builder.py`
- Consultar: `apps/analytics/models.py`
- Consultar: `apps/analytics/services/affiliate_parsers/amazon.py`
- Consultar: `apps/analytics/services/affiliate_parsers/mercadolivre.py`
- Consultar: `apps/analytics/services/affiliate_parsers/shopee.py`

- [ ] Confirmar no relatório que ML/Shopee continuam com link direto e atribuição nativa.
- [ ] Registrar que Amazon usa `/r` somente por compliance próprio, não como modelo geral de tracking.
- [ ] Registrar a granularidade atual de `AffiliateConversion`: oferta ou `external_ref`, marketplace, período, cliques, conversões, receita e comissão.
- [ ] Registrar as lacunas atuais: canal ausente em ML/Amazon, Shopee dependente de SubID e ingestão ainda não homologada com payload real.
- [ ] Não alterar nenhum arquivo nesta tarefa.

**Verificação:** `git diff --exit-code -- docs/LINK_POLICY.md docs/AFFILIATE_REPORTS_INGESTION.md apps/analytics/services/link_builder.py` deve retornar código 0.

### Tarefa 0.2: criar o protocolo de evidência

**Arquivo:**
- Criar: `docs/superpowers/evidence/affiliate-api-homologation-evidence-template.md`

- [ ] Criar template com seções fixas: marketplace, fonte, URL, data/hora, operação, pré-requisito, request redigido, response redigida, campos úteis, limites, custo, conclusão e hash do payload de teste.
- [ ] Proibir no template: access key, secret, token, cookie, `Authorization`, e-mail, telefone, nome de cliente e payload bruto de pedido.
- [ ] Definir que uma resposta GraphQL com erro de campo não prova falta de acesso; separar erro de autenticação, schema, permissão e regra de negócio.
- [ ] Definir que uma API de catálogo não é evidência de API de conversão.

**Verificação:** revisar o arquivo procurando `secret`, `token`, `cookie` e `Authorization`; esses termos só podem aparecer em uma seção de campos proibidos, nunca como valor.

---

## Fase 1: homologar Shopee Affiliate Open API

### Tarefa 1.1: validar credencial e endpoint sem expor dados

**Arquivos:**
- Consultar: `apps/marketplaces/services/shopee_affiliate_client.py`
- Consultar: `core/settings.py`
- Criar temporário: `/tmp/descontos-api-homologacao-shopee.py`

- [ ] Carregar Django e `ShopeeAffiliateClient` pelo ambiente existente.
- [ ] Confirmar somente a presença de `SHOPEE_AFFILIATE_APP_ID` e `SHOPEE_AFFILIATE_SECRET`, sem imprimir valores.
- [ ] Fazer uma chamada oficial de baixo impacto a uma operação documentada de catálogo/performance.
- [ ] Registrar apenas `authenticated_reachable`, status lógico, nome da operação, quantidade de nós e nomes de campos retornados.
- [ ] Classificar o resultado como autenticação válida, credencial inválida, permissão ausente, schema incompatível ou erro transitório.
- [ ] Remover o probe temporário depois da execução.

**Comando de verificação:**

```bash
.venv/bin/python manage.py shell -c "from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient; c=ShopeeAffiliateClient(); print(bool(c.app_id and c.secret));"
```

**Critério:** nenhum secret aparece na saída; uma falha de GraphQL precisa ser registrada com código e mensagem redigida, não tratada automaticamente como falta de acesso.

### Tarefa 1.2: validar a operação de geração de link com SubID

**Arquivos:**
- Consultar: `apps/analytics/services/link_builder.py`
- Consultar: `apps/marketplaces/services/shopee_link_generator.py`
- Testar: `apps/analytics/tests/test_link_builder_shopee.py`

- [ ] Usar um URL de produto de homologação já permitido pela conta, nunca um link escolhido para publicação.
- [ ] Executar `generateShortLink` com SubIDs de teste não associados a canal real, por exemplo `homologacao`, `teste_api` e `batch_test`.
- [ ] Confirmar que a resposta contém short link e/ou long link.
- [ ] Confirmar que os SubIDs estão presentes no resultado oficial sem expor a URL completa no relatório.
- [ ] Verificar que falha da API continua fazendo fallback direto, sem bloquear a coleta/publicação existente.
- [ ] Não ligar ou desligar flags de produção durante a homologação.

**Critério de aprovação:** geração de link oficial funciona, conserva os SubIDs e não exige redirect do descontos.bot.

### Tarefa 1.3: validar conversão, comissão e atribuição

**Arquivos:**
- Consultar: `apps/analytics/services/affiliate_parsers/shopee.py`
- Consultar: `apps/analytics/management/commands/ingest_affiliate_shopee.py`
- Consultar: `apps/analytics/models.py`
- Criar fixture redigida: `apps/analytics/tests/fixtures/shopee_conversion_report_redacted.json`
- Testar: `apps/analytics/tests/test_affiliate_parser_shopee.py`

- [ ] Localizar na documentação oficial da conta a operação vigente: `conversionReportV2`, `get_affiliate_performance` ou equivalente.
- [ ] Fazer uma consulta de leitura para uma janela mínima permitida, sem imprimir linhas individuais.
- [ ] Confirmar se o retorno contém: item/produto, order/conversão, status, comissão, valor da venda, data e SubIDs.
- [ ] Confirmar se `subId2` ou campo equivalente permite reconstituir canal e oferta.
- [ ] Comparar o schema real com `COLUMN_ALIASES` e com o parser atual.
- [ ] Criar fixture mínima e redigida com uma conversão fictícia estruturalmente equivalente, sem dados reais.
- [ ] Testar conversão confirmada, pendente, cancelada, comissão zero, item órfão, SubID ausente e reimportação idempotente.

**Critério de aprovação:** o sistema consegue associar conversão e comissão a `Offer` ou `external_ref` e, quando o SubID estiver presente, ao `SocialChannel`, sem intervenção manual.

### Tarefa 1.4: validar limites, atraso, custo e permissão

- [ ] Consultar documentação oficial da Open API e registrar rate limits, paginação e janela temporal.
- [ ] Confirmar se a conta precisa de aprovação adicional para relatório de conversão/performance.
- [ ] Confirmar se há cobrança por uso; se a documentação não informar, registrar `não publicado`, nunca `gratuito`.
- [ ] Fazer no máximo duas chamadas adicionais controladas para testar paginação e janela vazia.
- [ ] Registrar atraso observado/documentado entre conversão e disponibilidade no relatório.
- [ ] Definir cadência segura de ingestão sem exceder o limite.

**Gate Shopee:** só marcar `HOMOLOGADO_API` se comissão e atribuição forem retornadas pela API real. Catálogo e geração de short link sozinhos resultam em `PARCIAL_CATALOGO_APENAS`.

---

## Fase 2: homologar Amazon Creators API e Reporting API

### Tarefa 2.1: confirmar disponibilidade para Amazon.com.br

**Fontes:**
- `https://associados.amazon.com.br/creatorsapi/docs/en-us/introduction`
- `https://associados.amazon.com.br/creatorsapi/docs/en-us/onboarding`
- `https://associados.amazon.com.br/creatorsapi/docs/en-us/api-reference`
- `https://affiliate-program.amazon.com/creatorsapi/docs/en-us/get-started/using-sdk`

- [ ] Confirmar que a conta está inscrita no programa de Associados para Amazon.com.br.
- [ ] Registrar se a conta pode registrar uma aplicação na Creators API.
- [ ] Confirmar se o locale BR expõe a Reporting API, e não apenas catálogo.
- [ ] Confirmar requisitos de aprovação, partner tag, access key, secret e escopos.
- [ ] Confirmar se a Reporting API é incluída no acesso padrão ou se depende de habilitação adicional.
- [ ] Registrar custo como `não publicado` se não houver preço oficial.

**Gate:** se a documentação BR não expuser a Reporting API, abrir uma verificação autenticada no Associates Central ou uma solicitação oficial de suporte; não inferir disponibilidade a partir da documentação global.

### Tarefa 2.2: validar Creators API de catálogo separadamente

**Arquivos:**
- Consultar: `apps/marketplaces/services/` e integração Amazon existente
- Testar: testes do conector Amazon existente

- [ ] Fazer uma chamada de leitura de catálogo com ASIN de homologação.
- [ ] Confirmar que a API não está sendo confundida com dados de vendas.
- [ ] Registrar campos de produto, preço, imagem e link, mas não classificá-los como comissão/conversão.
- [ ] Registrar limites de requisição, requisitos de aprovação e locale.

**Critério:** catálogo aprovado não encerra a homologação do P0.

### Tarefa 2.3: validar Reporting API e relatórios S3

**Arquivos:**
- Criar: `apps/analytics/services/amazon_creators_reporting.py`
- Criar: `apps/analytics/tests/test_amazon_creators_reporting.py`
- Consultar: `apps/analytics/services/affiliate_parsers/amazon.py`

- [ ] Antes de criar o conector, obter a operação oficial de geração/listagem de relatório e os tipos de relatório disponíveis para Amazon.com.br.
- [ ] Criar uma requisição de relatório para janela mínima de homologação, se permitido pela conta.
- [ ] Consultar o status do relatório sem polling agressivo.
- [ ] Baixar o objeto S3 apenas pelo mecanismo oficial retornado pela API.
- [ ] Não persistir o relatório bruto no repositório; salvar somente hash, tamanho, cabeçalhos redigidos e resultado do parser.
- [ ] Confirmar se o relatório contém ASIN/produto, cliques, pedidos, unidades, receita, ganhos/comissão, status e Tracking ID.
- [ ] Confirmar se o Tracking ID permite atribuição ao canal/oferta ou somente agregação da conta.
- [ ] Reusar `AffiliateConversion` e o parser atual somente depois que o schema real for conhecido.

**Critério de aprovação:** geração e download automáticos funcionam para Amazon.com.br e os campos de receita/comissão podem ser associados pelo menos ao ASIN e ao período.

### Tarefa 2.4: validar atraso, ajuste e cancelamento

- [ ] Confirmar a cadência mínima do relatório.
- [ ] Confirmar se comissões são preliminares ou aprovadas.
- [ ] Confirmar como reprocessar ajustes, devoluções e cancelamentos.
- [ ] Testar reimportação do mesmo relatório por hash.
- [ ] Testar reimportação de período já existente com valores corrigidos.

**Gate Amazon:** `HOMOLOGADO_API` somente se a Reporting API estiver acessível no locale BR. Se só o relatório manual estiver disponível, marcar `BLOQUEADO_SEM_FONTE_OFICIAL` para autonomia, mesmo que o parser manual continue funcionando.

---

## Fase 3: homologar Mercado Livre sem scraping

### Tarefa 3.1: separar APIs gerais de APIs de afiliados

**Fontes:**
- `https://developers.mercadolivre.com.br/pt_br/api-docs-pt-br`
- `https://www.mercadolivre.com.br/ajuda/metricas-programa-afiliados_32755`
- `https://www.mercadolivre.com.br/knowledge-hub/32755`

- [ ] Inventariar os endpoints oficiais encontrados para catálogo, anúncios, seller e pedidos.
- [ ] Marcar explicitamente cada endpoint como inadequado para atribuição de afiliado quando não retornar `affiliate_id`, SubID, comissão ou conversão atribuída.
- [ ] Procurar na documentação oficial por API de afiliados, métricas, conversão, earnings, commission e report.
- [ ] Registrar a ausência de endpoint documentado como resultado de pesquisa, sem transformar isso em prova de que nenhum acesso privado existe.

### Tarefa 3.2: verificar opções oficiais da conta/programa

- [ ] Verificar no portal se existe exportação oficial de relatório por URL, API, e-mail, SFTP ou integração autorizada.
- [ ] Verificar se o SubID usado pelo projeto aparece no relatório oficial ou apenas no link.
- [ ] Verificar se existe filtro por SubID, item, campanha ou período.
- [ ] Verificar se existe documentação de acesso para parceiros aprovados que não esteja no portal público.
- [ ] Se for necessário contato com suporte, registrar pergunta objetiva: “Existe API, webhook, exportação programática ou envio automático de relatório de conversões/comissões para afiliados do Brasil, com identificação por SubID?”
- [ ] Não coletar resposta via scraping, DevTools ou automação de sessão.

### Tarefa 3.3: decidir o status do Mercado Livre

- [ ] Se houver API ou exportação oficialmente automatizável, criar adapter em `apps/analytics/services/` e testes de contrato.
- [ ] Se houver apenas painel manual, manter o parser existente e marcar `BLOQUEADO_SEM_FONTE_OFICIAL`.
- [ ] Se houver relatório automático por e-mail, criar ingestão de anexo com hash, parser existente e mailbox dedicado, desde que permitido pelo programa.
- [ ] Não criar redirect próprio, tracking próprio ou scraper headless como alternativa.

**Gate Mercado Livre:** o P0 só será marcado como resolvido para ML se o dado de comissão/conversão puder chegar automaticamente de uma fonte oficial.

---

## Fase 4: contrato comum de ingestão e reconciliação

### Tarefa 4.1: definir contrato de fonte

**Arquivos:**
- Criar: `apps/analytics/services/affiliate_source_contract.py`
- Testar: `apps/analytics/tests/test_affiliate_source_contract.py`

- [ ] Definir enum de status da fonte: `api`, `official_report`, `manual_only`, `unknown`.
- [ ] Definir campos obrigatórios de evidência: `source`, `source_record_id`, `period_start`, `period_end`, `status`, `commission`, `revenue`, `currency`, `offer_ref`, `channel_ref`, `raw_payload_sha256`.
- [ ] Definir `attribution_confidence` como `confirmed`, `partial`, `aggregate`, `unknown`.
- [ ] Rejeitar qualquer import que não declare a origem e o período.
- [ ] Manter `social_channel=None` quando a fonte não fornecer canal; não inferir canal por proximidade temporal.

### Tarefa 4.2: definir reconciliação sem alterar a política de links

**Arquivos:**
- Consultar: `apps/analytics/models.py`
- Consultar: `apps/analytics/services/affiliate_parsers/`
- Criar testes: `apps/analytics/tests/test_affiliate_reconciliation.py`

- [ ] Associar por SubID/Tracking ID quando a fonte fornecer esse campo.
- [ ] Associar por ASIN/MLB/item ID quando a fonte só fornecer produto.
- [ ] Manter conversão órfã quando não houver correspondência inequívoca.
- [ ] Nunca associar por título aproximado se houver múltiplos produtos possíveis.
- [ ] Preservar o snapshot da oferta enviado: preço, cupom, marketplace, canal e data.
- [ ] Reprocessar períodos corrigidos sem duplicar conversões.

### Tarefa 4.3: definir classificação de rentabilidade

- [ ] `confirmed`: comissão e conversão retornadas pela fonte oficial.
- [ ] `partial`: comissão retornada, mas sem produto ou canal inequívoco.
- [ ] `aggregate`: valor da conta/período sem atribuição de oferta.
- [ ] `unknown`: nenhum dado oficial automatizado disponível.
- [ ] Impedir que `aggregate` ou `unknown` seja usado como recompensa por oferta individual.
- [ ] Registrar limitações por marketplace no dashboard e no relatório de homologação.

---

## Fase 5: testes e homologação final

### Tarefa 5.1: testes unitários de parsers e contratos

- [ ] Rodar testes específicos de Shopee, Amazon e Mercado Livre.
- [ ] Adicionar fixtures redigidas para respostas de sucesso, erro de permissão, schema incompatível, timeout, paginação, janela vazia, cancelamento e reimportação.
- [ ] Confirmar que secrets nunca aparecem em logs ou exceções.

Comandos:

```bash
.venv/bin/python manage.py test \
  apps.analytics.tests \
  apps.marketplaces.tests \
  --keepdb
```

### Tarefa 5.2: probes reais controladas

- [ ] Executar um probe por marketplace, com limites mínimos e somente leitura.
- [ ] Não usar o produtor `run_bot` nem o consumidor WhatsApp.
- [ ] Não gerar lote, não publicar e não alterar flags.
- [ ] Guardar evidência redigida com status e hashes.
- [ ] Remover arquivos temporários após revisão.

### Tarefa 5.3: verificação de segurança e configuração

- [ ] Confirmar que `.env` não está rastreado:

```bash
git ls-files .env .env.*
```

- [ ] Confirmar que nenhuma chave aparece em diff, logs ou arquivos de evidência:

```bash
git grep -n -E 'SHOPEE_AFFILIATE_SECRET|ACCESS_KEY|SECRET_KEY|Authorization:|Bearer ' -- ':!*.pyc' || true
```

- [ ] Rotacionar credenciais que tenham sido expostas em qualquer saída compartilhada antes de continuar a homologação.
- [ ] Verificar que todos os logs de erro redigem headers e payloads.

### Tarefa 5.4: produzir decisão final

**Arquivo:**
- Criar: `docs/API_AFFILIATE_HOMOLOGATION_REPORT.md`

- [ ] Preencher uma seção por marketplace.
- [ ] Incluir links oficiais, data da pesquisa e evidências redigidas.
- [ ] Separar claramente catálogo, geração de link, cliques, conversão, receita e comissão.
- [ ] Declarar acesso real, acesso documentado mas não habilitado e ausência de API.
- [ ] Declarar se o P0 está resolvido integralmente, parcialmente ou bloqueado.
- [ ] Registrar a decisão arquitetural: manter links diretos e usar somente atribuição nativa.

---

## Ordem de execução recomendada

1. Fase 0 — contrato, segurança e evidência.
2. Fase 1 — Shopee, porque já existe cliente e credencial configurados.
3. Fase 2 — Amazon, aproveitando a nova Reporting API documentada.
4. Fase 3 — Mercado Livre, sem scraping e sem redirect.
5. Fase 4 — contrato comum somente depois de conhecer os schemas reais.
6. Fase 5 — testes, relatório e decisão de P0.

## Resultado esperado

O resultado não precisa ser “todas as APIs funcionam”. O resultado correto pode ser:

```text
Shopee: homologada
Amazon: homologada ou bloqueada por acesso regional
Mercado Livre: bloqueado por ausência de fonte oficial automatizável
```

Nesse caso, o projeto terá uma resposta técnica verificável para o P0 e saberá exatamente quais marketplaces podem alimentar rentabilidade real sem quebrar políticas de afiliados.
