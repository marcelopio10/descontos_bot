# Operação Local — descontos.bot

> Como manter o bot rodando 24/7 em uma máquina local (Linux/WSL2) e detectar quando ele para.

## Componentes

| Componente | O que faz | Frequência |
|---|---|---|
| `run_bot` | Scraping + curadoria + envio WhatsApp/Telegram + geração assets Instagram | Loop contínuo (90–180min entre ciclos, janela 06:00–24:00 BRT) |
| `fetch_clicks` | Importa cliques do Vercel KV para a tabela `ClickEvent` no SQLite | A cada 30 minutos |
| `healthcheck.sh` | Confere se o último ciclo do `run_bot` é recente | Sob demanda (ou via cron externo) |

## Pré-requisitos

- Linux com `systemd` (Ubuntu 22.04+ ou WSL2 com systemd habilitado)
- Python virtualenv em `.venv/` (ajustar paths nos `.service` se diferente)
- Repositório clonado em `~/descontos.bot` (ajustar `WorkingDirectory` se diferente)
- `.env` com `KV_REST_API_URL` / `KV_REST_API_TOKEN` para `fetch_clicks`

Verifique se o systemd user está disponível:

```bash
systemctl --user status
```

Se retornar "Failed to connect to bus", siga as instruções abaixo para WSL2.

### WSL2 sem systemd (alternativa)

Edite `/etc/wsl.conf` na distro:

```ini
[boot]
systemd=true
```

Reinicie o WSL no PowerShell:

```powershell
wsl --shutdown
```

## Instalação dos services

Cria diretório de unidades user-level e copia os arquivos:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/run-bot.service       ~/.config/systemd/user/
cp scripts/fetch-clicks.service  ~/.config/systemd/user/
cp scripts/fetch-clicks.timer    ~/.config/systemd/user/
systemctl --user daemon-reload
```

Garante que processos do usuário continuem rodando após logout:

```bash
sudo loginctl enable-linger $USER
```

## Ativação

```bash
# Bot principal (loop contínuo)
systemctl --user enable --now run-bot.service

# Sync de cliques (timer dispara a cada 30min)
systemctl --user enable --now fetch-clicks.timer
```

## Verificação

```bash
# Status dos serviços
systemctl --user status run-bot.service
systemctl --user status fetch-clicks.timer

# Logs em tempo real
journalctl --user -u run-bot.service -f
journalctl --user -u fetch-clicks.service -n 50

# Logs gravados em arquivo (alternativa)
tail -f logs/run-bot.log
tail -f logs/fetch-clicks.log

# Healthcheck manual
bash scripts/healthcheck.sh
```

Saída esperada do healthcheck quando tudo está OK:

```
OK: último ciclo há 47min (2026-05-27T14:23:11.234567+00:00)
```

## Como funciona o healthcheck

O `run_bot` grava `data/last_cycle.txt` ao fim de cada ciclo (mesmo quando não há ofertas elegíveis). O `healthcheck.sh` verifica se esse timestamp é mais recente que `MAX_AGE_HOURS` (default 4h).

Use em cron externo ou monitor para receber alerta:

```cron
# /etc/cron.d/descontos-bot-healthcheck
*/15 * * * * marce bash /home/marce/descontos.bot/scripts/healthcheck.sh || echo "descontos.bot parado" | mail -s "Alerta" voce@email.com
```

## Operações comuns

```bash
# Parar tudo
systemctl --user stop run-bot.service fetch-clicks.timer

# Reiniciar bot (após mudança de código/config)
systemctl --user restart run-bot.service

# Disparar fetch_clicks manualmente (fora do timer)
systemctl --user start fetch-clicks.service

# Ver quando o próximo fetch_clicks vai rodar
systemctl --user list-timers fetch-clicks.timer

# Desabilitar (sem desinstalar)
systemctl --user disable --now run-bot.service fetch-clicks.timer
```

## Rotina sugerida de revisão semanal

> Bloco G entrega o endpoint `/api/weekly` que automatiza essa rotina. Até lá, manual.

Toda segunda-feira de manhã:

1. `bash scripts/healthcheck.sh` — confirma bot vivo
2. Abrir `https://descontos.bot/dashboard.html` — conferir cliques Amazon (7d) e top ofertas
3. Abrir painel Mercado Livre Afiliados > Relatórios — conferir cliques por SubID (`dbot_wa_main_*`, `dbot_ig_*`, etc.) e segmentação por canal
4. Conferir `logs/run-bot.log` por erros recorrentes
5. Avaliar se cadência (canais ativos, intervalo, janela) precisa ajuste

## Troubleshooting

**`run-bot.service` reinicia em loop:**
- Cheque `logs/run-bot.log` para a causa real
- Confirme que o virtualenv em `.venv/` existe e tem todas as deps (`.venv/bin/pip install -r requirements.txt`)
- Confirme que `.env` está populado

**`fetch-clicks` falha silenciosamente:**
- `journalctl --user -u fetch-clicks.service -n 100`
- Confirme `KV_REST_API_URL` e `KV_REST_API_TOKEN` em `.env`
- Teste manual: `python3 manage.py fetch_clicks --dry-run --limit 10`

**Healthcheck falha mas o bot parece rodar:**
- O bot pode estar travado em scraping ou aguardando janela de distribuição
- Cheque se o último log do `run_bot` é mais recente que `data/last_cycle.txt` — se sim, está rodando mas não terminou um ciclo completo ainda
