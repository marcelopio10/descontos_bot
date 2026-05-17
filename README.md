# descontos.bot

Plataforma local em Django para coletar, normalizar, selecionar e distribuir ofertas de marketplaces brasileiros no WhatsApp.

## Status

MVP fechado em 2026-05-17. Operação real em produção desde 2026-05-15 (WhatsApp validado, compliance Amazon Associates coberta tecnicamente nas Fases 0-7 — ver `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`). Sprint 6 (hardening: blacklist de termos, score mínimo, revisão extra de logs e segurança) e Fase 8 do plano Amazon (contingência por rejeição) ficam no backlog pós-MVP — ver `docs/PLANO_EXECUCAO_SPRINTS.md` seção "Backlog Pós-MVP".

## Stack

| Componente | Tecnologia |
|------------|------------|
| Backend | Python 3.11+ e Django 6.0.4 |
| Banco | SQLite em `data/descontos_bot.db` |
| WhatsApp | `wa_service/` com Node.js 20 LTS e Baileys |
| Scraping | `requests.Session` e BeautifulSoup |
| Operação | Scheduler local via `python3 manage.py run_bot` |

Docker, FastAPI, Uvicorn, SQLAlchemy, Jinja2 e bancos externos não fazem parte do MVP.

## Fluxo Local

```text
scrapers Mercado Livre/Amazon
  -> normalização Django
  -> SQLite local
  -> publicação automática de site/offers.json quando houver diff real
  -> curadoria por desconto
  -> mensagem pt-BR
  -> wa_service
  -> WhatsApp
  -> histórico de entregas
```

## Preparação

Crie o ambiente Python e instale as dependências:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Prepare o banco e os dados iniciais:

```bash
python3 manage.py migrate
python3 manage.py seed_initial_data --target "Nome exato do grupo WhatsApp"
```

O banco oficial é sempre `data/descontos_bot.db`. O projeto configura WAL e `foreign_keys=ON` ao abrir conexões SQLite.

## Dry Run

Use `dry_run` para validar scraping, seleção e mensagens sem enviar WhatsApp e sem gravar entregas:

```bash
python3 manage.py run_bot --dry-run --once
```

Para usar somente as ofertas já salvas no banco:

```bash
python3 manage.py run_bot --dry-run --once --skip-scraping
```

## Execução Contínua

O scheduler local roda ciclos contínuos com sleep randômico entre 90 e 180 minutos, configurável nas chaves `cycle_min_minutes` e `cycle_max_minutes`.

```bash
python3 manage.py run_bot --dry-run
```

Para envio real, inicie o WhatsApp em outro terminal e remova `--dry-run` somente após validação do PO:

```bash
cd wa_service
npm run dev
```

```bash
python3 manage.py run_bot
```

A distribuição real é bloqueada entre 00:00 e 06:00 BRT. Logs operacionais são gravados em `logs/bot.log`.

Para conferir o intervalo configurado sem dormir:

```bash
python3 manage.py run_bot --dry-run --once --skip-scraping --show-next-interval
```

## Publicação do Site

Ao final de cada captura executada por `run_bot` ou `scrape_marketplace`, o projeto chama o publisher automaticamente quando `PUBLISH_OFFERS_AFTER_CAPTURE=true`. O serviço gera o payload a partir do SQLite, compara os dados reais com `site/offers.json` ignorando apenas o timestamp `generated_at`, e só atualiza o arquivo quando há mudança nas ofertas publicáveis.

Com `PUBLISH_OFFERS_PUSH=true`, uma alteração real gera commit `chore: publish offers json` e executa `git push origin <branch>`, disparando o deploy da Vercel pelo Git. Sem diff real, não há commit nem push. Em `--dry-run`, a publicação automática é ignorada.

Controle por ambiente:

```env
PUBLISH_OFFERS_AFTER_CAPTURE=true
PUBLISH_OFFERS_PUSH=true
PUBLISH_OFFERS_BRANCH=main
OFFERS_JSON_OUTPUT_PATH=site/offers.json
```

Para publicar manualmente, o comando continua disponível:

```bash
python3 manage.py publish_offers --push
```

## WhatsApp

Contrato local do serviço:

- `GET /status`: retorna conexão e QR quando aplicável.
- `POST /send-message`: envia texto e imagem opcional para o destino configurado.

Variáveis e detalhes ficam em `docs/WA_SERVICE_CONTRACT.md` e `docs/ENVIRONMENT.md`.

### Troubleshooting

- WhatsApp desconectado: rode `cd wa_service && npm run dev`, acesse `GET /status` e pareie o QR.
- Grupo não encontrado: confirme se `SocialChannel.target` contém o nome exato ou identificador aceito pelo serviço.
- Oferta não enviada: verifique `Delivery` no Admin; falhas não contam como envio concluído.
- Nenhuma oferta elegível: reduza temporariamente `min_discount_percentage` ou rode scraping com `--max-pages 1`.
- CAPTCHA ou HTML bloqueado: aguarde e rode localmente em rede residencial, mantendo delays conservadores.

## Verificação

Antes de encerrar sprint ou abrir PR:

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
```

Consulte também `docs/CHECKLIST_PRE_MERGE.md`. 
