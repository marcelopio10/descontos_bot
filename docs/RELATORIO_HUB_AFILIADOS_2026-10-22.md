# Relatório — Hub de afiliados do ML como fonte de coleta (2026-10-22)

Status: **implementado e validado sem gravação; não está em produção.** A ativação depende da aprovação do operador.

## Resumo

O "Selecionados para você" do hub de afiliados entra como quarto ramo da coleta do Mercado Livre, ao lado de categorias `/ofertas`, busca direcionada e radar de concorrente. A flag `affiliate_hub_enabled` vale `0` por padrão, então nada muda até alguém ligar.

Teste real (só leitura, flag ligada apenas em memória, motor afiliado neutralizado):

| Métrica | Resultado |
|---|---|
| Chamadas ao hub por ciclo | 16 (8 categorias × relevância + comissão extra), ~65 s com intervalos de 2,0–4,5 s |
| Cards recebidos | 288 |
| Aceitos no scraper (desconto mínimo e teto da categoria) | 161 |
| Após filtros de categoria (`cycle_limit` etc.) | 114 |
| Erros de normalização | 0 |
| Com comissão extra | 87 de 114 |
| Novos no banco | 52 (62 já conhecidos; 46 vistos nas últimas 24 h; 3 enviados nos últimos 7 dias) |
| Por categoria | casa 25, tecnologia 20, infantil 15, beleza 15, sem categoria fixa (moda/esportes, vão ao classifier) 39 |
| Imagem e nota | 114 de 114 |

Links: um produto de catálogo (`/p/`) e um produto de vendedor (`user_product`, convertido para a URL do anúncio) geraram link `meli.la` pelo motor afiliado atual, e os links abriram o produto certo, sem bloqueio.

## Alterações (não commitadas)

- `scrapers/mercado_livre.py`: `scrape_affiliate_hub()`, chamada ao hub, leitura dos cards, conversão de `user_product` para URL de anúncio, regras da categoria antes do motor afiliado, interrupção e alerta `ml_cookie_expirado` em 401/403.
- `apps/scraping/services/adapters.py`: ramo `_affiliate_hub_payloads()` (só Mercado Livre), flags `affiliate_hub_enabled` (padrão 0) e `affiliate_hub_extra_commission_enabled` (padrão 1), contagem `hub=` no log `collect_summary`, dedup preservando os sinais do hub. Leitura da flag com falha mantém o hub desligado.
- `apps/marketplaces/services/search_provenance.py`: origem `affiliate_hub` permitida.
- `docs/MERCADOLIVRE_AFFILIATE_HUB.md`: operação, ligar/desligar, monitoramento e limitações.

As alterações de ontem no mesmo arquivo (sessão logada na coleta e detecção de tela de login/desafio) continuam no diff, também sem commit.

## Verificação

- `manage.py check`: sem problemas. `makemigrations --dry-run`: sem mudanças. `git diff --check`: ok.
- Testes existentes de scraping, normalizador ML e normalizador de ofertas: 96 executados, 95 ok. A falha restante (`test_directed_queries_failure_is_logged_instead_of_silenced`) já existia: vem de alteração local anterior que passou a registrar só o tipo da exceção no log da busca direcionada.
- Nenhuma oferta foi gravada pelo teste e nenhum alerta real foi enviado. O `run-bot.service` não foi reiniciado (PID 1497001, desde 21/10 20:17).

## Riscos e limitações

1. Rota interna do portal, sem documentação: pode mudar sem aviso. O ramo falha fechado e não derruba o restante da coleta.
2. Mesma sessão `ML_COOKIE`: se ela vencer, caem scraper, hub e links afiliados juntos (com alerta).
3. Link `/p/` cai na oferta vencedora do catálogo; se o vendedor recomendado for outro, preço e comissão extra podem diferir do card.
4. O card não traz vendedor nem reputação.
5. A curadoria ainda não usa comissão nem selo para priorizar; os sinais ficam no `raw_payload`.
6. Cerca de 114 itens a mais por ciclo para a curadoria e até ~100 chamadas a mais ao motor afiliado por ciclo.

## Para colocar em produção (requer autorização)

1. Reiniciar `run-bot.service` para carregar o código novo (com a flag em 0, nada muda).
2. Ligar `affiliate_hub_enabled=1` (comando em `docs/MERCADOLIVRE_AFFILIATE_HUB.md`).
3. Acompanhar o primeiro ciclo: `collect_summary ... hub=`, `ScrapingRun` do ML, ofertas `collection_source=affiliate_hub`, curadoria e envios.
4. Rollback: `affiliate_hub_enabled=0`, efetivo no ciclo seguinte, sem reinício.

## Próximos passos sugeridos

- Usar `commission_pct`, `extra_commission` e `highlight` na pontuação da curadoria.
- Avaliar URL do anúncio (em vez de `/p/`) quando o card for de comissão extra.
- Paginação além da primeira página por categoria, se o volume pedir.
