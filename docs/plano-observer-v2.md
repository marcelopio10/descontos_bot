# Plano: Extensão do Observer — Dimensões P0/P1

## 1. Mapeamento da Arquitetura Atual

| Camada | Arquivo | Tecnologia | Função |
|--------|---------|------------|--------|
| Coleta | `wa_service/src/observer.ts` | TypeScript/Baileys | Coleta mensagens WA, buffer em JSON |
| Ingestão | `apps/market_intel/services/ingestion.py` | Python/Django | Upsert mensagens no DB via parser |
| Parser | `apps/market_intel/services/parser.py` | Python/regex | Extrai marketplace, preço, cupom, labels, hints |
| Modelo | `apps/market_intel/models.py` | Django ORM | `ObservedWhatsAppMessage`, `MarketIntelDailyReport` |
| Relatório | `apps/market_intel/services/reports.py` | Python | Agrega em 3 blocos + `analyzed_offers` |
| Publicação | `publish_market_intel_report` mgmt command | Python | Gera `site/market-intel.json` |

Campos atuais do `ObservedWhatsAppMessage`:
- parsed_marketplace, parsed_price, parsed_original_price, parsed_discount_pct
- parsed_coupon, editorial_labels (JSON), scraper_hints (JSON)

Labels existentes: urgencia, prova_social, cupom, imagem, ate_50, ate_100, ate_300, acima_300
Hints existentes: categoria:*, termo:*, faixa_preco:*
Marketplaces existentes: amazon, mercadolivre, shopee, magalu, aliexpress, desconhecido

## 2. Schema Estendido

Novos campos em `ObservedWhatsAppMessage` (todos null-safe, sem quebrar existentes):

### P0-1: Sinais de engajamento (coletados pelo wa_service, null para WA)
- reacoes (PositiveIntegerField, null=True)
- visualizacoes (PositiveIntegerField, null=True)
- encaminhamentos (PositiveIntegerField, null=True)
- comentarios (PositiveIntegerField, null=True)
- repostado (BooleanField, null=True)
- qtd_repostagens (PositiveIntegerField, null=True)
- fixado (BooleanField, null=True)

### P0-2: Mecânica de preço
- parcelamento (PositiveSmallIntegerField, null=True)
- parcelado_sem_juros (BooleanField, null=True)
- pix (BooleanField, null=True)
- pix_desconto_pct (DecimalField 5,2, null=True)
- cashback (BooleanField, null=True)
- cashback_valor (DecimalField 10,2, null=True)
- menor_preco (BooleanField, null=True)
- cupom_tipo (CharField max_length=20, blank=True)  # percentual | valor_fixo | frete_gratis
- parsed_coupon já equivale a cupom_codigo

Novas labels: desconto_30, desconto_50, desconto_70, parcelado_sem_juros, pix, cashback, menor_preco, frete_gratis

### P0-3: Padrões de copy e formato
- emoji_densidade (DecimalField 4,2, null=True)
- emojis_top (JSONField, default=list)
- tem_headline (BooleanField, null=True)
- tem_de_por (BooleanField, null=True)  # já coberto por parsed_original_price
- tem_cta (BooleanField, null=True)
- cta_termos (JSONField, default=list)
- tipo_midia (CharField max_length=20, blank=True)  # foto_oficial|banner_proprio|video|carrossel|texto
- tamanho_mensagem (PositiveIntegerField, null=True)
- usa_caixa_alta (BooleanField, null=True)
- usa_negrito (BooleanField, null=True)  # detecta *texto* markdown-like

### P1-5: Marketplace mais rico
- marketplace_dominio_desconhecido (CharField max_length=500, blank=True)  # domínio não classificado
- programa_entrega (CharField max_length=20, blank=True)  # full|prime|frete_gratis

Novos marketplaces: shein, americanas, casas_bahia, centauro, netshoes, kabum

### P1-6: Marca dentro da categoria
- marca (CharField max_length=80, blank=True)

Nova label: marca:<nome>

### P1-4: Cadência e timing
- Sem novos campos no modelo; horário e dia derivados de `sent_at` no relatório

### P1-7: Análise de cobertura
- Sem novos campos no `ObservedWhatsAppMessage`; cross-query com `Offer`

## 3. Migração

Apenas campos aditivos (null=True/blank=True). Nenhuma coluna existente é alterada ou removida.
→ Migration `0002_observer_v2_fields.py` com todos os novos campos.
→ Retrocompatibilidade total: campos novos são null/blank, código existente ignora.

## 4. Estratégia de Implementação (PRs incrementais)

### PR1: Modelo + Parser + Relatórios (P0-2, P0-3, P1-5, P1-6)
- Migration com novos campos
- Estender `parser.py`: novas regex, labels, hints, brand extraction
- Estender `reports.py`: novos blocos de agregação
- Atualizar `ALLOWED_LABELS`, `ALLOWED_HINTS`, `ALLOWED_MARKETPLACES`
- Testes para cada nova extração
- Version bump 1.1 → 2.0

### PR2: Sinais de engajamento (P0-1)
- Estender `wa_service/src/observer.ts`: campos de engajamento no buffer
- Estender `ingestion.py`: persistir campos de engajamento
- Relatório: bloco "Sinais de engajamento"

### PR3: Análise de cobertura (P1-7)
- Cross-reference `ObservedWhatsAppMessage.urls` ↔ `Offer.product_url`
- Novo bloco "Cobertura (gap)" com métricas

### PR4: Cadência e timing (P1-4)
- Derivar horário/dia de `sent_at`
- Frequência por grupo, lag de cobertura
- Heatmap horário×dia

## 5. Formato do Payload v2.0

O payload existente (version 1.1) permanece idêntico nos blocos atuais.
Novos blocos são adicionados no mesmo nível:

```json
{
  "version": "2.0",
  "report_type": "incremental_market_intel",
  "...campos atuais inalterados...",

  "mecanica_preco": {
    "desconto_30": 5,
    "desconto_50": 14,
    "desconto_70": 2,
    "pix": 9,
    "parcelado_sem_juros": 12,
    "cashback": 3,
    "menor_preco": 4,
    "cupom_por_tipo": {"percentual": 7, "valor_fixo": 4, "frete_gratis": 2},
    "por_marketplace": {
      "mercadolivre": {"desconto_50": 8, "pix": 5, ...},
      ...
    },
    "por_categoria": {...}
  },

  "copy_e_formato": {
    "emoji_densidade_media": 3.2,
    "emojis_top": [{"emoji": "🔥", "count": 18}, ...],
    "tem_headline_pct": 0.65,
    "tem_cta_pct": 0.40,
    "cta_termos_top": [{"termo": "corre", "count": 12}, ...],
    "tipo_midia": {"foto_oficial": 15, "texto": 8, ...},
    "tamanho_mensagem_media": 320,
    "usa_caixa_alta_pct": 0.52,
    "usa_negrito_pct": 0.30,
    "engajamento_por_copy": [...]
  },

  "sinais_engajamento": {
    "top_por_reacoes": [...],
    "engajamento_medio_por_marketplace": {...},
    "engajamento_medio_por_categoria": {...},
    "nota": "Sinais de engajamento indisponíveis para grupos WhatsApp (plataforma não expõe)."
  },

  "cadencia_e_timing": {
    "heatmap_horario_dia": [...],
    "frequencia_por_grupo": [...],
    "sazonalidade": [...]
  },

  "marketplace_detalhado": {
    "contagem": {...},
    "dominios_desconhecidos": [...],
    "programa_entrega": {...}
  },

  "marcas_por_categoria": {
    "categoria:moda": [{"marca": "nike", "count": 5}, ...],
    ...
  },

  "cobertura": {
    "ofertas_nao_cobertas": 11,
    "taxa_sobreposicao": 0.38,
    "exclusivas_concorrente": 6,
    "backlog_curadoria": [...]
  }
}
```

## 6. Regras de Degradacao Graciosa

- Sinais de engajamento indisponíveis (WA não expõe) → campos null → excluídos de médias/rankings
- Sem preço "de" → desconto e labels de faixa de desconto = null
- Mensagem só-texto, sem imagem → tipo_midia = "texto"
- Domínio desconhecido → marketplace = "desconhecido" + dominio armazenado em marketplace_dominio_desconhecido
- Cupom sem tipo identificável → cupom_tipo = "" (vazio, não null)