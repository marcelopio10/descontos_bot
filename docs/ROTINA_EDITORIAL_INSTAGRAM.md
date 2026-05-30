# Rotina Editorial Mínima — Instagram @descontos.bot

> Documento oficial da Sprint 4 — Instagram Operacional e Status Editorial.
> Versão: 1.0
> Owner: Tião Macalé (Comunicação / Social Media)

---

## 1. Objetivo

Transformar o Instagram de fábrica de assets em canal operacional de aquisição.
Esta rotina padroniza o que publicar, quando publicar e como registrar, garantindo
consistência editorial mesmo com publicação manual.

---

## 2. Volumes Semanais

| Formato | Frequência | Total/semana | Janela recomendada |
|---|---|---|---|
| Story | 3/dia | 21 | 10h, 14h, 19h BRT |
| Feed ou Carrossel | 1/dia | 7 | 12h ou 18h BRT |
| Reel | 1/semana | 4/mês | Quinta ou sexta, 18h |

**Regra geral:** publicar conteúdo apenas entre 06:00 e 23:59 BRT.
Respeitar a janela de silêncio do projeto (00:00-06:00 BRT).

---

## 3. Critérios de Priorização de Ofertas

Aplicar na ordem abaixo ao escolher qual oferta publicar:

1. **Imagem com qualidade visual** — foto nítida, sem artefatos, fundo claro, produto centralizado. Pular ofertas com imagem borrada, recorte estranho ou proporção distorcida.
2. **Preço com destaque real** — desconto >= 20% e preço final visivelmente abaixo do mercado. Descontos irreais (100% OFF, valores zerados) são bloqueados.
3. **Marketplace variado** — alternar Amazon e Mercado Livre. Nunca publicar 3 conteúdos seguidos do mesmo marketplace.
4. **Produto com apelo sazonal ou visual** — priorizar categorias com alto potencial de clique: eletrônicos, casa, moda, beleza. Evitar produtos nichados demais no início.
5. **Recência da oferta** — ofertas mais recentes (menos de 72h) têm prioridade. Se o banco tem 2.900+ ofertas ready, rodar gerador sempre no comando `--top N` para pegar as mais frescas.

**Checklist rápido antes de publicar cada conteúdo:**

- [ ] Oferta tem asset em disco? (`.png` existe em `media/instagram/`)
- [ ] Link de afiliado no `.txt` está íntegro? (contém `tag=desconto.bot-20`)
- [ ] Imagem legível em mobile? (fonte e preço visíveis sem zoom)
- [ ] Marketplace está variado em relação ao último post/story?
- [ ] Preço e produto batem com o link?

Se um item falhar, pule a oferta. Escolha a próxima da fila.

---

## 4. Fluxo Diário

### 4.1 Manhã — Preparação (5 min)

1. Rodar gerador de stories para o dia:
   ```bash
   python3 manage.py generate_instagram_story --top 3
   ```
2. Rodar gerador de feed/carrossel:
   ```bash
   python3 manage.py generate_instagram_post --top 1
   ```
3. Verificar os assets gerados em `media/instagram/stories/` e `media/instagram/feed/`.
4. Selecionar as 3 melhores ofertas aplicando os critérios da seção 3.
5. Separar os arquivos `.png` + `.txt` correspondentes.
6. Se for semana de reel, reservar a melhor oferta visual para o reel.

### 4.2 Publicação — 3 momentos

| Horário | Formato | Observação |
|---|---|---|
| 10h BRT | Story 1 | Pico matinal de mobile. Oferta com apelo forte. |
| 14h BRT | Story 2 + Feed/Carrossel | Almoço / pausa. Feed publica primeiro, story minutos depois. |
| 19h BRT | Story 3 | Pico noturno. Oferta de maior desconto. |

**Feed/Carrossel:** publicar junto com o story das 14h. O feed fica no grid permanente,
o story dá tração imediata.

### 4.3 Encerramento — Registrar no Admin

Após cada publicação manual:

1. Abrir o Django Admin (`/admin/apps/social_posts/instagrampost/`).
2. Localizar o `InstagramPost` correspondente (pelo `offer_id`, nome do arquivo ou data de geração).
3. Alterar status de `ready` para **`posted`**.
4. Salvar. O campo `posted_at` é populado automaticamente.

Se a oferta foi deliberadamente **rejeitada** (não passou nos critérios editoriais),
marcar como `rejected` com uma nota breve (ex.: "imagem borrada", "preço inconsistente").

---

## 5. Calendário Semanal Modelo

| Dia | Stories | Feed/Carrossel | Extra |
|---|---|---|---|
| Seg | 3 | Feed | — |
| Ter | 3 | Feed | — |
| Qua | 3 | Carrossel | Carrossel (3-5 imagens) alterna com feed. |
| Qui | 3 | Feed | **Reel** — produzir e publicar. |
| Sex | 3 | Feed | Oferta de maior apelo visual da semana. |
| Sáb | 3 | Carrossel | Pode antecipar ofertas de domingo. |
| Dom | 3 | Feed | Volume reduzido (opcional, apenas 1 story). |

**Nota:** Domingo é facultativo. Se não publicar, compensar na segunda com 1 extra.

---

## 6. Produção de Reel (1x/semana)

O reel é o formato de maior alcance orgânico no Instagram.

### Fluxo semanal

1. **Quarta (tarde):** escolher a oferta com melhor apelo visual da semana.
2. **Quarta (tarde):** preparar roteiro curto (15s-30s).
   - Abertura: produto + preço.
   - Meio: destaque do desconto (ex.: "de R$ 199 por R$ 129").
   - Fim: CTA — "Link na bio" ou "Toque no link do story".
3. **Quinta (manhã):** gravar/editar e publicar às 18h.

### Template de roteiro

```
[0-5s] Take rápido do produto + "Achado do bot hoje"
[5-15s] Detalhe do desconto + destaque visual do preço
[15-20s] "Corre que ainda tem" + CTA
[20-25s] Tela final com @descontos.bot
```

### Alternativa sem gravação

Se não houver capacidade de gravar vídeo, usar:
- Imagem estática da oferta + texto animado (ferramenta: CapCut, InShot, Reels nativo do Instagram).
- Ou carrossel extendido (6-8 slides) como substituto.

---

## 7. Integração com o Admin

### Transições de status

```
ready → posted   (publicado manualmente)
ready → rejected (rejeitado na curadoria)
posted → ready   (desfazer — só com validação do PO)
```

### Regras

- **Obrigatório:** todo conteúdo publicado deve ser marcado como `posted` no Admin.
- O campo `posted_at` é automático ao salvar como `posted`.
- Conteúdo rejeitado recebe `rejected` + motivo breve no `publish_error`.
- É seguro rejeitar várias ofertas de uma vez com a ação em lote do Admin.

### Ações em lote no Admin

As ações "Marcar como postado" e "Marcar como rejeitado" estão disponíveis no
Admin para selecionar múltiplos `InstagramPost` de uma vez.

---

## 8. Métricas de Sucesso (Semanais)

| Métrica | Meta inicial | Meta sprint 4 |
|---|---|---|
| Stories publicados | 21/semana | 21/semana |
| Feed/Carrossel publicados | 7/semana | 7/semana |
| Reels publicados | 1/semana | 1/semana |
| Taxa de `posted` no Admin | 100% dos publicados | 100% |
| Marketplaces diferentes na semana | >= 2 | >= 2 |
| Stories com sticker de link | 100% | 100% |

### Métricas de aquisição (acompanhar depois)

- Cliques nos links dos stories.
- Novos seguidores/semana.
- Cliques no link da bio (via `links.json`).

---

## 9. Riscos e Contingências

| Risco | Impacto | Ação |
|---|---|---|
| Gerador não produz assets | Dia sem conteúdo | Rodar manualmente com `--force` ou usar oferta de dias anteriores |
| Instagram derrubar conta | Zero publicações | Pausar tudo. Reportar ao PO. Não tentar recriar conta sem autorização |
| Erro no link de afiliado | Link quebrado | Não publicar. Marcar como `rejected` com nota "link inválido" |
| Falta de tempo para publicar 3 stories | Furo na grade | Publicar ao menos 1. Compensar no dia seguinte com 1 extra |

---

## 10. Perguntas Frequentes

**Posso publicar a mesma oferta em story e feed no mesmo dia?**
Sim. Desde que os formatos sejam diferentes (story curto / feed com legenda).

**E se o asset .png sumir do disco mas o InstagramPost estiver ready?**
Rodar `generate_instagram_story --top 1` para a oferta específica ou recriar com o comando da oferta correta.

**Preciso publicar exatamente nos horários da tabela?**
Não. São janelas recomendadas. O importante é respeitar a janela de silêncio e não concentrar 3 stories num intervalo de 30 minutos.

**Reel precisa ser vídeo original?**
Não. Use foto + texto animado se não houver vídeo. O importante é manter o formato Reel para o algoritmo.

---

## 11. Referências

- [HOWTO — Publicar ofertas no Instagram Stories](../docs/HOWTO_PUBLICAR_OFERTAS_INSTAGRAM.md) — passo a passo manual de publicação.
- [GROWTH PLAN](../docs/GROWTH_PLAN_DESCONTOS_BOT.md) — visão geral das sprints.
- Django Admin → `/admin/apps/social_posts/instagrampost/` — gerenciamento de status.
- Assets em disco → `media/instagram/stories/`, `media/instagram/feed/`.
