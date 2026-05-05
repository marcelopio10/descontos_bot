# Checklist Pré-Merge — descontos.bot

Use este checklist antes de encerrar qualquer sprint ou abrir PR.

## Regras Obrigatórias

- [ ] Não há Docker, Dockerfile, docker-compose ou runtime equivalente.
- [ ] Não há FastAPI, Uvicorn, SQLAlchemy ou Jinja2.
- [ ] O banco oficial continua sendo `data/descontos_bot.db`.
- [ ] SQLite mantém WAL e `foreign_keys=ON`.
- [ ] `.env` não foi versionado.
- [ ] Sessões WhatsApp não foram versionadas.
- [ ] Sessões Instagram não foram versionadas.
- [ ] Bancos SQLite locais não foram versionados.
- [ ] Logs locais não foram versionados.
- [ ] Código Python usa identificadores em inglês, PEP 8, 4 espaços e aspas simples.
- [ ] Código TypeScript usa identificadores em inglês, 2 espaços e aspas simples.
- [ ] UI, `verbose_name`, mensagens ao operador e documentação operacional estão em pt-BR.

## Verificação Técnica

Execute:

```bash
python3 manage.py check
```

Se houver alteração em models, execute:

```bash
python3 manage.py makemigrations --dry-run
```

Se houver alteração em `wa_service/`, execute:

```bash
cd wa_service
npm test
```

## Produto

- [ ] A janela de silêncio 00:00-06:00 BRT continua bloqueando distribuição.
- [ ] O limite de ofertas por ciclo permanece global.
- [ ] `dry_run` não envia mensagens reais.
- [ ] Credenciais continuam em `.env`, nunca em código ou banco em texto claro.
- [ ] Scrapers preservam sessão HTTP persistente, headers realistas, delays conservadores e detecção de CAPTCHA.
