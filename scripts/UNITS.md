# Inventário de unidades systemd (2026-08-23)

Estes arquivos são a **cópia versionada do que roda de verdade** em
`~/.config/systemd/user/`. Antes de 2026-08-23 não eram: `run-bot.service`
apontava para `%h/descontos.bot`, diretório que não existe nesta máquina, e não
trazia `--channel whatsapp_principal` — quem o instalasse teria um serviço que
não sobe e que, com o caminho corrigido, publicaria em **homologação** sem
avisar, porque o guard de produção só exige confirmação em canal de produção.

## Convenção

- **Caminhos absolutos, não `%h`.** É um deploy de máquina única
  (`/mnt/c/Users/marce/Documents/Projetos/descontos.bot`), e `%h` deu a falsa
  impressão de portabilidade enquanto escondia divergência.
- **Comentário mora no lado versionado.** Produção manda em `ExecStart`,
  caminhos e agendamento; o repositório guarda o porquê. `check-units-drift.sh`
  compara ignorando comentários justamente por isso.
- **Verificar antes de instalar:** `scripts/check-units-drift.sh` (sai 1 se
  houver divergência ou unidade rodando fora do Git).

## Serviços contínuos

| Unidade | O que faz |
|---|---|
| `run-bot.service` | Scheduler local: scraping, curadoria e envio. Roda com `--ai-curation-required` desde 2026-08-23 |
| `evolution-adapter.service` | Bridge WhatsApp entre o `run_bot` e a Evolution API |

## Timers

| Unidade | Agendamento | O que faz |
|---|---|---|
| `backup-db.timer` | 04:30 | Backup do SQLite com cópia offsite |
| `logrotate-descontos.timer` | 05:10 | Rotação de logs (`copytruncate`) |
| `ingest-ml-afiliados.timer` | segunda 06:20 | Vendas do painel de afiliados do ML |
| `relatorio-receita-semanal.timer` | segunda 07:10 | Relatório publicado × vendido |
| `descontos-bot-central-report.timer` | 08:15 | Relatório sanitizado na Central Hermes |
| `lembrar-metrica-canal.timer` | segunda 09:00 | Cobra a contagem de membros do WhatsApp |
| `coupons-daily.timer` | 09:15 BRT | Pipeline diário de cupons |
| `market-intel.timer` | 22:00 BRT | Relatório diário de market intel |
| `radar-concorrente.timer` | 20 min | Resolve links dos grupos observados |
| `processar-fila-envio.timer` | 30 min | Processa a fila desacoplada |
| `publish-telegram.timer` | 30 min | Publica no canal Telegram |
| `fetch-clicks.timer` | 30 min | Sincroniza cliques do Vercel KV |
| `consumir-fila-whatsapp-v2.timer` | 90 min | Consome lote pronto e envia ao WhatsApp |
| `reap-curation-runs.timer` | 1 h | Encerra `CurationRun` presa em `running` |
| `check-observer-health.timer` | 6 h | Saúde da coleta do observer |
| `descontos-bot-guardian.timer` | 15 min | Monitor do profile Hermes |

## Unidades cujo código não está neste repositório

`descontos-bot-guardian` e `descontos-bot-central-report` executam scripts em
`~/.hermes_v2/profiles/descontos-bot/scripts/`. Estão versionadas aqui para o
inventário ficar completo — **um clone limpo não as faz funcionar**. Versionar os
scripts é decisão de quem mantém o profile Hermes.

## Unidades que rodam na máquina e não são deste projeto

Não entram no inventário nem são cobradas pelo `check-units-drift.sh`:
`central-hermes-dashboard-sync` (Central Hermes), `hermes-gateway`
(infraestrutura compartilhada), `pioexplica-telegram-listener` (projeto
pio.explica) e `launchpadlib-cache-clean` (sistema).

## Instalação

```bash
cp scripts/<unidade>.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now <unidade>.timer
```

`systemd-analyze --user verify` acusa "marked executable / world-writable" em
todos os arquivos: é característica do `/mnt/c` (drvfs monta 777), não erro de
sintaxe.
