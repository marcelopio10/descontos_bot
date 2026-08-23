# O laço publicado × vendido, e a procedência da métrica de público (2026-08-23)

> Itens 7, 8 e 9 da Onda 1 do diagnóstico v2. O item 7 é o laço que faltou por
> 2,5 meses: sem cruzar publicação com venda, o corte da faixa de R$ 500 levou
> 82 dias para aparecer. O item 8 conserta o dado de público, que estava errado
> por 12×. O item 9 é decisão do dono — aqui fica a medição que ela exige.

---

## Item 7 — Relatório semanal publicado × vendido

`apps/analytics/services/revenue_loop.py` · `manage.py relatorio_receita_semanal`
· `relatorio-receita-semanal.timer` (segunda 07:10, depois da ingestão das 06:20)

### Os três recortes, em ordem de confiabilidade

| Recorte | Depende de | Confiabilidade |
|---|---|---|
| **Faixa de preço** | `saleValue` do painel × preço publicado | Alta — os dois lados sempre existem |
| **Categoria** | casamento venda↔oferta | Amostra — resolve ~58% das vendas |
| **Caminho de publicação** | `CuratedBatchItem.delivery` | Alta — a marca é estrutural |

A faixa de preço vem primeiro de propósito: é o recorte que teria pego a quebra
de junho, e é o único que não depende de casar venda com oferta.

### Quatro decisões de medição que mudam o número

1. **Só Mercado Livre.** É o único marketplace com venda a venda. Cruzar
   publicação de três marketplaces com venda de um produz denominador inflado —
   o relatório separa `deliveries_total` de `deliveries_ml` justamente para
   isso.
2. **Preço é o da publicação, não o de hoje.** Vem do `PriceHistoryEntry` mais
   recente até o envio, com fallback para `Offer.current_price` quando a oferta
   foi coletada e publicada no mesmo ciclo. Sem isso, uma oferta que mudou de
   preço depois do envio migra de faixa retroativamente e o recorte mente.
   (RESTR-05: histórico é uso interno; nada daqui vai para caption.)
3. **Compra própria nunca entra.** Excluída de todo cálculo, e o total excluído
   aparece nos avisos.
4. **Status imaturo é avisado, não escondido.** Janela recente vem quase toda em
   `IN_REVIEW`; o relatório reporta aprovado e em revisão lado a lado e avisa
   quando a fatia em revisão passa de 30%.

### O que a primeira execução mostrou (8 semanas, 28/06 a 23/08)

```
faixa                 envios      %  vendas    comissão      %     R$/1k
até R$ 100               957   41.8       5    R$ 49.19   39.3     51.40
R$ 100 a 300            1010   44.1       4    R$ 75.96   60.7     75.21
R$ 300 a 500             218    9.5       0        R$ 0    0.0      0.00
R$ 500 a 1.000            95    4.1       0        R$ 0    0.0      0.00
acima de R$ 1.000         10    0.4       1        R$ 0    0.0      0.00
```

**13,6% dos envios estão em faixas que não geraram um centavo na janela.** Não é
conclusão ainda — são 10 vendas, e a faixa reaberta só entrou em produção em
23/08 —, mas é exatamente o formato de sinal que faltava.

Para comparação, a mesma consulta em maio (03/05 a 31/05), antes dos tetos:

```
R$ 500 a 1.000           322   13.5       3   R$ 240.21   40.1    745.99
```

**40% da comissão do mês em 13,5% dos envios.** É a quebra de junho vista pelo
instrumento que deveria tê-la detectado na época.

### Onde o resultado é gravado

`data/exports/receita_semanal/AAAA-MM-DD.json` — diretório ignorado pelo git de
propósito: o relatório tem receita e **não pode** ir para `site/`, que é
publicado. O timer também dispara um resumo para o Telegram do operador.

---

## Item 8 — Procedência da contagem de membros

O problema não era o número estar velho: era não haver como distinguir palpite de
medição depois de gravado. Os três únicos registros de `MetricaCanalDiaria`
diziam 1.240 membros no WhatsApp (real ~100) e 860 no Telegram (real 6).

**O que mudou:**

- Campo `fonte` (`medido_api` · `informado_dono` · `estimado`), com default
  **`estimado`** — quem não declara procedência não ganha o benefício da dúvida.
  Migration `0006`; os três registros antigos passaram a `estimado`
  automaticamente.
- `--fonte` virou obrigatório em `registrar_metrica_canal`.
- **A curva do painel ignora ponto estimado** e reporta quantos descartou em
  `unverified_points`. Hoje a curva está vazia e o contador em 3 — que é o
  resultado correto: curva vazia é melhor que curva errada, porque a errada
  induz decisão.
- `lembrar-metrica-canal.timer` (segunda 09:00) cobra o dono quando a última
  medição verificada passa de 8 dias. O WhatsApp não tem endpoint de contagem no
  adapter Evolution — o que dá para automatizar é a cobrança, não a medição.

Só o WhatsApp é acompanhado: o Telegram saiu do acompanhamento na revisão 2.2 do
diagnóstico, por não ser canal de distribuição.

### Defeito encontrado no caminho (corrigido)

O alerta do operador é enviado com `parse_mode=HTML`, e **nenhuma mensagem com
`<` chegava**: o Telegram devolvia HTTP 400 (`Unsupported start tag`) e o alerta
sumia em log de warning — justamente quando havia algo a avisar. Apareceu porque
a instrução do lembrete contém `--membros <N>`, mas afetava qualquer alerta com
`<`, `>` ou `&` no dado (mensagem de erro com `<html>`, título de produto com
`&`). `apps/analytics/services/alertas.py` passou a escapar a mensagem do caller,
mantendo a marcação da própria função. Regressão coberta em `test_alertas.py`.

---

## Item 9 — A medição que a decisão exige

A decisão é do dono: aceitar o selector legado como fallback e medir os dois
caminhos, ou ligar `--ai-curation-required` e pausar o ciclo quando a IA falha.

**Envios do WhatsApp por caminho, por semana:**

| Semana | Legado | Curadoria IA | % legado |
|---|---|---|---|
| 2026-28 | 17 | 381 | 4,3% |
| 2026-29 | 40 | 589 | 6,4% |
| 2026-30 | 42 | 217 | 16,2% |
| 2026-31 | 9 | 478 | 1,8% |
| 2026-32 | 48 | 244 | 16,4% |
| 2026-33 | 92 | 212 | **30,3%** |

A tendência é de alta, e os dois piores dias são 21/08 (46%) e 22/08 (39%) —
antes das correções de prompt e do `OPENCODE_GO_API_KEY`. Em 23/08, depois delas,
o legado ficou em **0%** de 22 envios. Um dia não é série.

**Motivos de falha da curadoria, últimos 7 dias:** o grosso é "nenhum item
aprovado e selecionado pela IA" (dezenas de ocorrências, com lotes de 15 a 50
candidatas), mais 9 de autenticação Hermes e 7 encerradas pelo reaper.

**O que o relatório do item 7 mede sobre isso:** na janela de 8 semanas, o
selector legado responde por 20,1% dos envios e por **zero** venda casada. Com 10
vendas na janela, isso é indício, não prova — a leitura fica honesta só depois de
algumas semanas de série.

O relatório semanal passa a trazer essa quebra por padrão, que é o que a opção
"aceitar e medir" exige para não ser só aceitar.
