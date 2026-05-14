# HOWTO — Publicar ofertas no Instagram Stories

## 1. Objetivo

Padronizar a publicação manual de ofertas no Instagram do `@descontos.bot` a partir
dos arquivos gerados automaticamente pelo gerador de posts. O processo deve ser
rápido, repetível e seguro, mesmo para quem nunca mexeu no Instagram antes.

Cada oferta vira:

- 1 imagem `.png` (1080×1920) — o visual do Story.
- 1 arquivo `.txt` com o link de afiliado e o resumo do produto.

A publicação **é sempre manual**. Nenhuma automação faz upload no Instagram.

## 2. Onde encontrar os arquivos

Todos os arquivos ficam dentro de `media/instagram/stories/` na raiz do projeto.

```
media/
└── instagram/
    └── stories/
        ├── amazon_b08cjd52bv_story.png   ← imagem
        ├── amazon_b08cjd52bv_story.txt   ← link e metadados
        ├── amazon_b07l5vnt9q_story.png
        ├── amazon_b07l5vnt9q_story.txt
        └── ...
```

Outros formatos podem aparecer em `media/instagram/feed/` e
`media/instagram/carousel/`. Para Stories use apenas a pasta `stories/`.

## 3. Como identificar qual link pertence a qual imagem

Imagem e link sempre têm **o mesmo nome base**, mudando apenas a extensão.

| Imagem                        | Arquivo do link                |
|-------------------------------|--------------------------------|
| `amazon_b08cjd52bv_story.png` | `amazon_b08cjd52bv_story.txt`  |
| `amazon_b07l5vnt9q_story.png` | `amazon_b07l5vnt9q_story.txt`  |
| `meli_mlb1234567_story.png`   | `meli_mlb1234567_story.txt`    |

A regra de nomeação é:

```
{marketplace}_{id_da_oferta_no_marketplace}_story.{png|txt}
```

Para Amazon o `id_da_oferta` é o **ASIN** (ex.: `B08CJD52BV`).
Para Mercado Livre o `id_da_oferta` é o **MLB id** (ex.: `MLB1234567`).
Em letras minúsculas.

Se houve conflito de nome, aparecem variações sufixadas: `..._story-2.png`,
`..._story-3.png` — sempre acompanhadas do `.txt` correspondente.

## 4. Conteúdo de um arquivo .txt

```
Produto: Moda vintage: Manual prático para selecionar e confeccionar roupas no estilo...
Marketplace: Amazon
Link: https://www.amazon.com.br/dp/8520438091?linkCode=sl2&tag=descontos.bot-20&linkId=...&utm_source=instagram&utm_medium=story&utm_campaign=offer_2526
Gerado em: 2026-05-14 17:14
```

- **Link** é sempre o link de afiliado direto. Para Amazon vem com o
  `tag=descontos.bot-20` e parâmetros UTM `utm_source=instagram` e
  `utm_medium=story`. Esse é o link que **deve ir no sticker** do Story.
- **Nunca use** o link de redirecionamento via site (`/r?slug=...`) no
  Instagram. Esse formato é exclusivo do canal WhatsApp.

## 5. Publicação pelo navegador desktop

1. Abra `https://www.instagram.com` no navegador.
2. Entre na conta `@descontos.bot` (a conta correta — sempre confira o avatar antes
   de prosseguir).
3. No explorador de arquivos do sistema operacional, abra
   `media/instagram/stories/`.
4. Escolha a oferta que vai publicar. Anote o **nome base** do arquivo (ex.:
   `amazon_b08cjd52bv_story`).
5. Abra o `.txt` de mesmo nome base. Selecione e copie a linha do `Link:`
   (apenas a URL, sem o prefixo "Link: ").
6. No Instagram, clique no botão "Criar" (ícone "+" no topo).
7. Escolha **Story**. Faça upload da imagem `.png` correspondente.
8. Na tela de edição do Story, clique no ícone de stickers e selecione **Link**.
9. Cole a URL copiada do `.txt` no campo do link.
10. Personalize o texto do sticker (opcional) com algo curto, ex.: `Ver oferta`,
    `Comprar agora`. Não use frases sensacionalistas (ver §9).
11. Posicione o sticker em um lugar visível, sem cobrir o preço.
12. Confira no preview: produto, preço, marketplace e link batem com a mesma
    oferta? Se sim, clique em **Compartilhar no seu story**.

## 6. Publicação pelo celular

1. Transfira a imagem `.png` e o arquivo `.txt` para o celular. Opções:
   - AirDrop / Nearby Share.
   - Drive / Dropbox / OneDrive (pasta sincronizada).
   - Anexar em um e-mail para você mesmo.
   - Salvar a imagem direto da pasta `media/instagram/stories/` se o
     computador está sincronizado com a nuvem.
2. Abra o `.txt` no celular e copie o conteúdo da linha `Link:` (apenas a URL).
3. Abra o aplicativo do Instagram.
4. Toque na sua foto de perfil ou em "Seu story" para criar um novo Story.
5. Selecione a imagem `.png` da oferta na galeria.
6. Toque no ícone de sticker no topo e escolha **Link**.
7. Cole a URL copiada do `.txt` no campo. Opcionalmente edite o texto do
   sticker (curto, sem caixa-alta gritando).
8. Posicione o sticker num espaço livre da imagem.
9. Toque em **Concluído**.
10. Revise o preview — produto, preço e link consistentes?
11. Toque em **Seu story** para publicar.

## 7. Revisão de consistência imagem ↔ link

Antes de publicar confirme **na hora**:

- O **ASIN** que aparece na URL do `Link:` é o mesmo que aparece no nome do
  arquivo? Ex.: nome `amazon_b08cjd52bv_story.png` → URL deve conter
  `/dp/B08CJD52BV`.
- O **preço** do Story é o mesmo da página da Amazon ao abrir o link?
- O **marketplace** do Story (pill no canto superior direito) é o mesmo do
  campo `Marketplace:` do `.txt`.

Se qualquer um desses três pontos divergir, **não publique**. Volte ao
gerador de posts.

## 8. Adaptando a chamada do sticker (opcional)

A imagem já traz o CTA "toque no link acima". O texto do **sticker** do
Instagram pode reforçar isso. Opções aceitáveis:

- `Ver oferta`
- `Comprar agora`
- `Abrir na Amazon`
- `Pegar desconto`

Evite copiar a frase exata da imagem para não soar redundante.

## 9. Boas práticas — evitar cara de spam

- Máximo **1 emoji** por Story, e nunca no preço.
- **Zero pontos de exclamação** no sticker e no texto extra.
- Evite palavras gatilho de spam: `IMPERDÍVEL`, `ÚLTIMA CHANCE`, `CORRE`,
  `SÓ HOJE`, `URGENTE`. Use linguagem de curadoria: `Achado do bot`,
  `Preço caiu`, `Oferta monitorada`.
- Não publique a mesma oferta duas vezes no mesmo dia.
- Respeite a janela de silêncio do projeto: **não publicar entre 00:00 e
  06:00 BRT**.
- Não envie 5 stories seguidos do mesmo marketplace — alterne ofertas.

## 10. Checklist antes de publicar

- [ ] Estou na conta `@descontos.bot`.
- [ ] Imagem é a versão atual da oferta (mesma data no `.txt`).
- [ ] Link do `.txt` foi copiado **inteiro**, sem espaços no fim.
- [ ] Sticker de **Link** foi adicionado e cola a URL completa.
- [ ] Sticker está visível e não cobre o preço.
- [ ] ASIN da URL bate com o nome do arquivo da imagem.
- [ ] Preço do Story bate com o preço da página do produto.
- [ ] Sem ALL-CAPS gritando, sem `!`, sem mais de 1 emoji.
- [ ] Horário fora da janela 00:00–06:00 BRT.

## 11. Problemas comuns e como resolver

| Sintoma | Diagnóstico | Solução |
|---|---|---|
| Sticker de Link não aparece no Instagram | Conta sem o recurso liberado | Tente o app atualizado; em alguns casos o IG libera o Link sticker só após X seguidores. Enquanto isso, publique sem link e oriente "link na bio". |
| Link copiado abre página errada | Copiou texto antes/depois da URL | Reabra o `.txt` e selecione **apenas** o que vem após `Link: ` até o fim da linha. |
| Imagem aparece esticada ou cortada | Aplicativo redimensionou no upload | Confira que o arquivo foi enviado em 1080×1920 (proporção 9:16). Reenvie original sem editar. |
| Falta a imagem na pasta | Oferta não tinha `image_url` válida | Esperado. O gerador pula ofertas sem imagem. Procure outra. |
| `.txt` vazio ou só com `Link: ` | Oferta sem link de afiliado | Esperado. O gerador também pula. Procure outra. |
| Vários arquivos com sufixo `-2`, `-3` | Conflito de nome (oferta reprocessada) | Use a versão mais recente. Apague as antigas se preferir. |
| Preço da imagem está estranho (ex.: 100% OFF) | Oferta com dado bruto inconsistente | Não publique. Reportar/corrigir antes. |

## 12. Onde reportar problemas

- Bug no visual ou no `.txt` → abrir issue interna no repositório.
- Bug no link ou no ASIN → checar `apps/offers/models.py` (`Offer.affiliate_link`)
  e a fonte do scrape.
- Janela de silêncio bloqueando geração → ver
  `apps/distribution/services/execution_window.py`.

## 13. Onde rodar o gerador

```bash
# Story top 1 (maior desconto entre ofertas Amazon publicáveis)
python3 manage.py generate_instagram_story --top 1

# Story top 3 (terceiro maior desconto, etc.)
python3 manage.py generate_instagram_story --top 3
```

O comando imprime no terminal o caminho da imagem (`.png`) e do `.txt`. Esses
são os arquivos que você vai abrir para publicar.
