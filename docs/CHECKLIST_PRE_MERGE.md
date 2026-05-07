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

Se a mudança tocar compliance Amazon, site público, links de afiliado ou posts Instagram, execute:

```bash
python3 scripts/amazon_compliance_check.py
```

O script sobe um servidor HTTP local temporário para validar as rotas públicas do diretório `site/`.

## Produto

- [ ] A janela de silêncio 00:00-06:00 BRT continua bloqueando distribuição.
- [ ] O limite de ofertas por ciclo permanece global.
- [ ] `dry_run` não envia mensagens reais.
- [ ] Credenciais continuam em `.env`, nunca em código ou banco em texto claro.
- [ ] Scrapers preservam sessão HTTP persistente, headers realistas, delays conservadores e detecção de CAPTCHA.

## Amazon Associates

- [ ] Home pública responde HTTP 200, exibe disclosure Amazon e não contém linguagem proibida.
- [ ] `site/offers.json` contém disclosure e links Amazon com `tag=descontos.bot-20`.
- [ ] Página de oferta responde HTTP 200 e exibe disclosure, preço com timestamp e CTA patrocinado.
- [ ] `site/links.json` contém disclosure, 5+ itens e UTM `utm_source=instagram&utm_medium=bio`.
- [ ] `/links` ou `/links.html` responde HTTP 200 e exibe disclosure Amazon.
- [ ] Fonte primária `https://descontos-bot.vercel.app` foi cadastrada no portal Amazon Associates.
- [ ] Instagram oficial foi cadastrado no portal Amazon Associates com URL completa.
- [ ] Canal público de WhatsApp foi criado e cadastrado no portal Amazon Associates.
- [ ] Grupo fechado de WhatsApp foi removido das fontes do portal.
- [ ] 5+ ofertas foram publicadas manualmente no Instagram.
