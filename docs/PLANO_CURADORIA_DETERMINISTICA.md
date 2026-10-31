# Plano de execução — curadoria determinística e análise por coleta

## Objetivo e escopo

Dar ao operador controle explícito e auditável sobre o que é oferta forte, o que deve ser descartado e quais famílias/categorias devem ganhar ou perder prioridade. Exibir na seção descontos.bot da Central Hermes cada coleta completa, incluindo itens descartados e falhas. Usar concorrentes como fonte de oportunidades revalidadas e resultados reais como evidência, sem transformar opinião da IA em regra comercial obrigatória.

Este documento é um plano, não uma implantação. A Central Hermes não foi inspecionada nesta etapa; sua integração depende de localizar o repositório/serviço autorizado e verificar o contrato real de autenticação e atualização. Não alterar outro projeto/profile implicitamente.

## Regra bloqueante — produção preservada até autorização expressa

Nada deste plano pode mudar ou impactar a produção atual sem autorização expressa do operador. Aprovar o plano, desenvolver código ou validar uma etapa não constitui autorização para implantar ou ativar mudanças em produção. Esta regra prevalece sobre todas as fases e critérios de liberação abaixo.

- Até essa autorização, desenvolvimento e validação devem ocorrer em ambiente isolado, com dados de teste ou cópias sanitizadas, sem escrita no banco de produção, envio real, alteração de configurações/pesos/regras ativos, execução de migrações em produção, reinício de serviços ou publicação de artefatos consumidos pela operação atual.
- Não editar código, prompts ou arquivos utilizados pelos processos de produção em seu local ativo, mesmo sem reiniciar o serviço. Usar cópia de trabalho isolada; não presumir que uma mudança em disco só terá efeito após reinício.
- Instrumentação, novos coletores, revalidações e integração com a Central também estão sujeitos ao bloqueio: não podem introduzir carga adicional, jobs, chamadas externas ou dependências na operação atual sem autorização expressa. Flags desativadas não substituem essa autorização.
- Antes de qualquer ativação, apresentar escopo exato, impacto previsto, verificações e rollback, e aguardar autorização expressa para esse escopo. Autorização para uma etapa não autoriza automaticamente as seguintes.
- A produção deve continuar com o comportamento, os serviços, a cadência e as configurações atuais enquanto não houver essa autorização.

## Base existente confirmada

- `apps/scraping/models.py`: ScrapingRun e ScrapingItemResult já representam execuções e resultados por item, inclusive descarte, falha e ausência de Offer.
- `apps/offers/models.py`: Category já tem weight 1–10, is_active e exposure_quota_pct. Reutilizar sem presumir que is_active já bloqueia o seletor; implementar e auditar o comportamento desejado.
- `apps/curation/`: há decisões IA, snapshots, classificação, famílias, recorrência e optimizer, mas não rastreabilidade completa de todos os descartes pré-IA.
- `apps/analytics/models.py`: ClickEvent, AffiliateImportBatch e AffiliateConversion já existem; validar cobertura e atribuição efetivas antes de reutilizar como métricas comerciais.
- Há alterações locais extensas. Inventariar e preservar essas mudanças antes da implementação; não atribuir tudo a este plano.

## Contrato de decisão proposto

Separar três coisas: segurança/viabilidade, preferência editorial e prioridade de envio.

Ordem de precedência:

1. Gate obrigatório: conteúdo proibido, indisponibilidade, identidade inválida, preço ausente/inválido, restrição do canal/afiliado/compliance, silêncio 00:00–06:00 BRT e regras de não duplicação/republicação.
2. Bloqueio manual explícito de produto, família ou categoria. Bloqueio prevalece sobre prioridade; nunca é removido por IA ou peso positivo.
3. Classificação manual do produto como oferta forte, acompanhada de condições comerciais e validade.
4. Política determinística versionada de categoria/família e critérios de preço/qualidade/concorrência.
5. IA opcional: sugestões de categoria/família, revisão de texto e apoio analítico; não deve vetar silenciosamente uma oferta editorialmente aprovada. Riscos sugeridos pela IA devem ser separados da preferência editorial, ter evidência e trilha de revisão.

Uma oferta forte recebe prioridade, não autorização irrestrita para envio. Ainda exige revalidação e respeita gates obrigatórios. Limites de exposição/família continuam aplicáveis, mas explícitos, configuráveis e visíveis; a interface deve indicar quando impedem o envio.

A marcação forte não garante que todas as futuras ocorrências tenham bom preço. Guardar teto de preço ou condição de benefício, variação/SKU, evidência, autor, motivo e validade. Se não houver teto, limitar a decisão à ocorrência validada; para reutilização futura, solicitar condição comercial explícita.

Faixa de desconto anunciado e quantidade de avaliações devem ser separadas dos gates de segurança. Não permitir que um mínimo heurístico de desconto exclua silenciosamente um produto manualmente forte quando o preço final validado é vantajoso; definir substituição explícita por teto de preço/evidência. Não inventar economia se o preço de referência for desconhecido.

Estados da revisão: forte, neutra, desconsiderada e pendente. Ação forte por padrão vale para o produto identificado, não automaticamente para a categoria inteira. Bloqueio por família/categoria requer confirmação com prévia de impacto. Bloqueio de canal e bloqueio global devem ser distinguíveis.

## Fase 0 — baseline e preparação

- Inventariar mudanças locais e processos envolvidos, sem reiniciar serviços.
- Preservar a auditoria histórica e montar uma execução de referência com input/output/decisões/envios.
- Definir identidade do produto: marketplace, anúncio, canônico e variação, quando disponíveis. Não transferir marcações por título parecido sem confirmar identidade.
- Fechar o contrato da integração com a Central: leitura, ações autenticadas, atualização e isolamento de descontos.bot.

Aceite: diagnóstico reproduzível e contrato conhecido; nenhuma publicação ou alteração de outro projeto.

## Fase 1 — corrigir falsos bloqueios e registrar decisões

### Segurança

- Substituir bloqueio por substring por regras tokenizadas e contextualizadas, compartilhadas entre SQL/Python/pré/pós-IA conforme necessário.
- Separar título/descrição do produto de legenda e justificativa; não tratar qualquer menção em reason como prova de conteúdo proibido.
- Exigir tipagem correta no retorno IA, inclusive booleanos e scores, identidade e cobertura das candidatas esperadas.
- Reproduzir os casos armário, Armani, Armaf e brinquedo que imita adultos; confirmar que armas/conteúdo proibido continuam bloqueados.

### Auditoria

Registrar por execução e por ocorrência, antes de limitar/deduplicar o pool:
- identidade da coleta, occurrence/item, Offer quando existir e execução de curadoria;
- snapshot de preço, estoque, categoria, família, origem e evidências;
- estágio, resultado, código e motivo legível;
- regra/política, versão de código, configurações e instante;
- score/componentes, decisão bruta IA e decisão final, sem sobrescrever uma pela outra.

Motivos propostos: indisponível, preço inválido, cupom não verificado, bloqueio de segurança, veto manual, stale, republicação não permitida, cooldown, família saturada, afiliado com falha, score insuficiente, corte de pool, deduplicação e limite de lote. Diferenciar falha, descarte e pendência; registrar motivo principal e motivos adicionais sem dupla contagem.

Novas entidades de domínio, se necessárias, herdam TimestampedModel e usam apenas data/descontos_bot.db, WAL e foreign_keys=ON. Reutilizar ScrapingItemResult; não criar banco paralelo.

Aceite: cada ocorrência processada tem resultado rastreável, inclusive sem Offer; totais reconciliam e gates de segurança não regrediram.

## Fase 2 — categorias, famílias e revisão manual

- Corrigir classificação por palavras/atributos, incluindo gênero explícito, sem dependência artificial de adjacência.
- Separar brinquedo com tapete-pista de tapete doméstico e revisar famílias demasiadamente amplas.
- Persistir categoria/família automática, correção manual e versão do classificador. Correções manuais não podem ser apagadas pela coleta seguinte.
- Propor uma política de família e uma revisão de produto como novos conceitos, não símbolos já existentes no projeto.
- Reutilizar peso de categoria; acrescentar peso/exposição/cooldown configurável de família e estado de bloqueio explícito. Peso baixo não equivale a bloqueio.
- Mostrar prévia de impacto antes de ativar regra ampla: itens afetados, potenciais envios removidos e sobreposição com outras regras.
- Guardar histórico, autor, justificativa, vigência e versão; permitir desfazer gerando nova versão, sem apagar auditoria.

Aceite: marcar forte, desconsiderar, corrigir família e ajustar categoria gera uma decisão determinística repetível para ocorrências futuras do mesmo produto, respeitando validade e condições comerciais.

## Fase 3 — Central Hermes: gráficos por coleta e ações

Depende da auditoria da Fase 1 e das regras da Fase 2. Implementar a fonte de dados em descontos.bot e o consumidor somente no repositório autorizado da Central.

### Tela na seção descontos.bot

- Histórico de coletas por horário BRT, origem/marketplace, estado e versão da política.
- Uma visão individual por coleta, atualizada durante execução e consolidada ao terminar; mostrar progresso, completude e horário real da fonte.
- Gráfico do funil: encontrados, normalizados, revalidados, elegíveis, candidatos IA, selecionados e enviados. Não inventar denominador de achados que o provedor não expõe; declarar limitação.
- Barras por categoria/família, com separação de aceitos/descartados/pendentes e motivos.
- Dispersão preço final × score/prioridade com um ponto por ocorrência com dados disponíveis; cor por resultado e clique abrindo detalhes. Itens sem preço/score continuam na lista e em contagem própria; não atribuir valor zero fictício.
- Tabela completa e paginada, sem corte silencioso no top 50. Diferenciar ocorrências, produtos únicos e produtos repetidos entre buscas.
- Exibir todos os itens retornados/identificados pelos coletores instrumentados, incluindo atualização de Offer existente, duplicatas, descarte e falhas. Não prometer mostrar produtos que o provedor não retornou.
- Filtros por coleta, marketplace, concorrente, categoria, família, faixa de preço, motivo e estado de revisão. Exportação CSV segura.

### Ações na linha/detalhe

- Marcar oferta forte, incluindo teto de preço/condição, motivo e validade.
- Desconsiderar produto para envios futuros.
- Voltar a neutra ou desfazer regra.
- Corrigir categoria/família.
- Aumentar/reduzir prioridade e ajustar exposição/cooldown por família/categoria.
- Bloquear/desbloquear família/categoria mediante confirmação de impacto.

Escritas devem ir ao backend autenticado de descontos.bot, com autorização, proteção CSRF quando aplicável, idempotência e controle de versão contra edições concorrentes. Não editar JSON público nem conectar a Central diretamente ao SQLite. Não incluir credenciais, dados de remetentes ou saídas arbitrárias de providers no payload.

Salvar uma marcação nunca envia uma mensagem. Novas preferências afetam execuções futuras; o histórico permanece congelado. Veto manual novo também deve ser rechecado imediatamente antes de consumir um lote pendente, com auditoria do cancelamento. Não reordenar silenciosamente lotes já prontos.

Aceite: abrir uma coleta real, reconciliar totais com o banco, encontrar todos os itens nas páginas, salvar uma decisão, ler de volta sua versão e comprovar seu efeito em replay sem envio. Verificar endpoint servido e interface real, não somente um screenshot local.

## Fase 4 — concorrentes como candidatos revalidados

- Resolver IDs/URLs dos concorrentes com identidade e fonte auditáveis; título semelhante permanece provável.
- Corrigir parsing de moeda/cupom antes de usar preços para ranking.
- Coletar com sessão HTTP persistente, headers realistas, delays conservadores, detecção CAPTCHA e retry conservador. Não ampliar carga indiscriminadamente.
- Revalidar variação, estoque, preço, seller quando aplicável e possibilidade de gerar nosso link afiliado; nunca publicar link afiliado de concorrente como nosso.
- Guardar preço anunciado, preço consultado, preço final, frete conhecido/desconhecido, cupom, condições, elegibilidade, validade, evidência e horário.
- Sem verificar aplicação do cupom, indicar benefício não confirmado e não apresentar preço final como fato. Revalidar antes do envio quando a evidência tiver expirado.
- Encaminhar oportunidades fortes verificadas ao pool sem depender apenas de generic_fallback; registrar motivos das que ficarem fora.

Métricas distintas:
1. Composição alinhada: envios próprios alinhados / envios próprios no período, separando identidade exata e provável. Meta solicitada: pelo menos 85%.
2. Cobertura: produtos concorrentes distintos e elegíveis que também enviamos / produtos concorrentes distintos e elegíveis observados.
3. Latência: publicação concorrente até revalidação/envio próprio.

Mostrar completude por grupo e limitações; não usar só categorias para declarar alinhamento. Não completar meta enviando ofertas indisponíveis, inseguras ou artificialmente repetidas. Se não houver candidatas suficientes, reportar distância da meta e motivos.

Aceite: uma publicação concorrente real é resolvida, revalidada e rastreada até elegibilidade; comparar nossos envios sem confundir composições e coberturas.

## Fase 5 — calibrar com cliques e vendas

- Reutilizar ClickEvent e relatórios AffiliateConversion após verificar integridade, cobertura, atraso e granularidade por fonte.
- Medir envios, cliques rastreáveis, conversões confirmadas, comissão e resultados por categoria/família/produto.
- Filtrar previews/bots e duplicações na medida possível, explicitando método e limitações. Cliques não representam pessoas únicas automaticamente.
- Não calcular CTR sem impressões: usar cliques por envio como proxy devidamente rotulado. Não atribuir uma venda a uma mensagem específica se a fonte fornece somente período/produto.
- Manter não atribuído separado de zero venda, e dados atrasados separados de resultado final.
- O painel propõe ajustes com janela e amostra mínima definidas; operador aprova uma nova versão. Não alterar prioridades automaticamente no MVP.
- Reservar exposição controlada e configurável para categorias novas, evitando condená-las por falta de oportunidade de envio. Distinguir preferência comercial de evidência observada.

Aceite: rastrear clique real e relatório de venda confirmado até a granularidade que a fonte suporta; mudança de prioridade fica auditada e pode ser desfeita.

## Liberação e rollback

- Ordem: Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5. Assim o operador obtém cedo coleta completa e controle manual, antes da otimização automática.
- Introduzir flags para auditoria, política determinística e integração Central; inicialmente observar/replay sem publicar.
- Homologação controlada antes de produção; evitar comandos dry-run que coletam, escrevem, publicam site ou acionam push sem verificar seus efeitos.
- Rodar `.venv/bin/python manage.py check`, `.venv/bin/python manage.py makemigrations --dry-run`, verificações existentes relevantes, replay dos casos reais e checklist pré-merge. Não criar suíte automatizada como entregável do MVP. Se tocar links/compliance, rodar `python3 scripts/amazon_compliance_check.py`; se tocar wa_service, seguir sua verificação existente.
- Preservar UNIQUE de Delivery por offer/canal, silêncio 00:00–06:00 BRT, SQLite oficial, sessões e segredos. Não usar Docker nem stacks proibidas.
- Identificar configuração efetiva e obter autorização antes de reiniciar serviço ou ativar envio real. Não fazer commit/push sem solicitação.
- Rollback: desativar a política nova via flag e retornar à versão anterior, preservando histórico de revisão/auditoria e bloqueios de segurança. Toda reversão deve registrar versão e motivo.

## Definition of Done

1. Cada coleta instrumentada aparece na Central com totais reconciliados e lista integral de ocorrências.
2. Nenhuma candidata desaparece do funil sem estágio/motivo; lacunas do provedor são declaradas.
3. Produto forte ou desconsiderado gera regra persistente, versionada e verificável em execução futura; bloqueio manual prevalece sobre IA.
4. Correções de categoria/família e ajustes de peso/exposição sobrevivem à coleta seguinte.
5. Casos de falso bloqueio deixam de disparar sem liberar conteúdo proibido.
6. Concorrentes entram como oportunidades verificadas; preço/cupom não confirmado nunca é apresentado como confirmado.
7. Metas, cobertura e resultados comerciais usam denominadores e limitações explícitos.
8. UI real, backend, regras e efeito no funil são verificados; salvamento no painel não aciona envio.
