# Instagram — por que parou e o que falta para voltar (2026-08-23)

> Item 10 da Onda 2. O Instagram é o **único canal de topo de funil que existe**
> no projeto, e o diagnóstico v2 colocou aquisição como prioridade estrutural:
> o funil converte (R$ 1,34 por membro/mês, 4,3% da base clicando por dia) e não
> tem público — 99 pessoas no WhatsApp.

## O diagnóstico

Não é credencial. O preflight do Composio responde:

```
$ manage.py check_instagram_composio
Preflight OK | username=@descontos.bot | id=27176727021981283
```

Também não é geração: a fila tem **89 posts em `awaiting_post`**, o mais recente
gerado hoje. Contra **5 publicados**, o último em **2026-06-03**.

O que faltava era caminho de publicação em lote:

| Peça | Estado |
|---|---|
| `publish_instagram_post` | publica **um** post, com `--confirm-production` individual |
| Ação no Admin | publica um post por vez, manualmente |
| `telegram_handoff_listener` | **não está rodando** — sem unit systemd, sem processo |
| Timer de publicação | **não existe** |

Ou seja: publicar exigia alguém sentar e disparar post a post. Foi o que
aconteceu 5 vezes em junho e nunca mais.

## O achado que muda a prioridade

Rodando o publicador novo em simulação:

```
Fila: 89 em awaiting_post · 7 publicáveis agora · 82 descartados por idade ou oferta fora do ar
```

**Só 7 dos 89 posts ainda valem.** Os outros 82 descrevem ofertas que saíram do
ar ou envelheceram — publicá-los seria anunciar preço morto na conta que deveria
trazer público. O backlog não é um ativo represado; é entulho.

Isso reordena o trabalho: não adianta "desbloquear a fila". O que importa é
publicar **o que a geração produz hoje**, com cadência, e deixar o resto morrer.

## O que foi construído

`manage.py publicar_instagram_lote` — publica em lote a partir de
`awaiting_post`, com duas travas de propósito, porque o destino é a conta real
do dono:

1. **Simulação é o padrão.** Publicação real só com `--confirm-production`.
2. **Post velho não vai ao ar.** Descarta por idade do post (`--max-age-days`,
   default 3) e por oferta inativa ou fora da janela de recência.

A cota diária por formato reusa os tetos da `politica_cadencia` (3 stories, 1
feed), mas conta **o que foi publicado hoje**, não o que foi gerado — a política
existente responde à outra pergunta, e usá-la aqui liberaria a fila inteira num
dia só.

```bash
manage.py publicar_instagram_lote                              # simula
manage.py publicar_instagram_lote --limit 2 --confirm-production
manage.py publicar_instagram_lote --formato story --max-age-days 2
```

Cobertura em `apps/social_posts/tests/test_publicar_instagram_lote.py`, com o
Composio sempre mockado — nenhum teste pode publicar de verdade.

## O que depende do dono

1. **Autorizar a primeira publicação real.** Rodar com `--confirm-production` é
   ação na conta pública dele; não foi feita.
2. **Decidir se automatiza.** Existe o comando, não existe timer. Automatizar
   significa publicar sem revisão prévia caso a caso — decisão editorial, não
   técnica. Se for automatizar, o timer entra com `--limit` baixo e a cadência
   fica onde já está (Setting `instagram_story_daily_limit`).
3. **Decidir o destino dos 82 posts mortos.** Sugestão: marcar como `rejected`
   em lote, para a fila parar de mentir sobre o tamanho do estoque. Não fiz —
   mexe em dado do pipeline dele.
4. **Item 11 (CTA de entrada) depende de um link que não está em lugar nenhum**:
   não há convite do grupo de WhatsApp no `.env`, no `panel.Setting` nem no
   `site/index.html`. Sem ele, não há para onde mandar quem vier do Instagram.
