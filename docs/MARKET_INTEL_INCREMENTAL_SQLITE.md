# Inteligência de mercado incremental — fase SQLite

## Escopo

Esta fase materializa sinais do observer em SQLite. Não publica ofertas, não altera política de curadoria e não migra banco.

Fluxo:

```text
observer → ObservedWhatsAppMessage → ObservedOpportunity → LearningEvent
                                      ↓
                              MarketLearningSnapshot (shadow)
                                      ↓
                              observer_context sanitizado
```

## Operação

Micro-lote:

```bash
python3 manage.py process_market_intel_incremental
```

Dry-run sem escrita:

```bash
python3 manage.py process_market_intel_incremental --dry-run
```

Snapshot horário:

```bash
python3 manage.py build_market_learning_snapshot
```

Timers fornecidos, não ativados automaticamente:

- `scripts/market-intel-incremental.service`
- `scripts/market-intel-incremental.timer`
- `scripts/market-intel-snapshot.service`
- `scripts/market-intel-snapshot.timer`

Antes de instalar timers, corrigir `WorkingDirectory`, `EnvironmentFile` e `ExecStart` para o checkout real do ambiente. Não usar `%h/descontos.bot` em WSL quando o checkout estiver em `/mnt/c/...`.

## Garantias

- cursor SQLite por fonte e ID da última mensagem;
- reprocessamento idempotente;
- fingerprint por URL canônica; fallback por sinais normalizados;
- oportunidade agregada, sem texto/URL no snapshot;
- estado inicial sempre `shadow`;
- cliques, conversões e comissão permanecem `null` sem fonte oficial;
- observer nunca dispara envio diretamente;
- contexto sanitizado antes de chegar à curadoria.

## Limitações conhecidas

- endpoint atual devolve janela do observer; cursor evita reprocessamento local, mas não reduz a coleta remota;
- correspondência com catálogo e delivery ainda são métricas futuras;
- contagem de grupos por oportunidade fica conservadora na primeira versão;
- snapshot não autoriza promoção de política;
- Postgres será avaliado após observar frescor, duplicidade, match e qualidade em shadow.
