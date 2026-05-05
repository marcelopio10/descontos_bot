# Revisão Crítica do PRD — descontos.bot

## Resumo Executivo

O PRD está consistente na direção do produto, mas mistura três estados diferentes: sistema legado com scripts, arquitetura Django alvo e evolução futura com IA. Para execução segura por agentes, o documento precisa separar melhor o que já existe, o que será portado no MVP e o que é visão futura.

A principal recomendação é iniciar por uma sprint de estabilização técnica antes de implementar novas funcionalidades. O repositório atual contém `core/settings.py` com SQLite padrão em `db.sqlite3`, enquanto as regras exigem `data/descontos_bot.db`. O `orchestrator.py` também referencia módulos `apps.*` que não aparecem na árvore atual, o que indica que o plano não deve assumir o domínio Django já pronto.

## Inconsistências Encontradas

### 1. Caminho do SQLite

Regra do repositório:

```text
Usar SQLite exclusivamente em data/descontos_bot.db
```

Estado atual observado:

```text
core/settings.py -> BASE_DIR / 'db.sqlite3'
```

Impacto: qualquer implementação que rode migrations no estado atual criará banco fora do padrão obrigatório.

Correção recomendada: primeira sprint deve ajustar settings, criar `data/` quando necessário e habilitar WAL + `foreign_keys=ON`.

### 2. Módulo Django divergente no orquestrador

O `orchestrator.py` usa:

```python
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'descontos_bot.settings')
```

Mas o projeto atual expõe `core/settings.py`.

Impacto: o orquestrador tende a falhar antes de iniciar Django.

Correção recomendada: padronizar o módulo de settings para `core.settings`, salvo se o projeto for renomeado formalmente.

### 3. Apps de domínio citados, mas ausentes

O PRD e o `orchestrator.py` citam domínios como `apps.offers`, `apps.curation`, `apps.distribution` e `apps.panel`, mas a árvore atual não mostra esses apps.

Impacto: há risco de agentes implementarem em cima de referências inexistentes ou criarem estruturas incompatíveis.

Correção recomendada: criar uma sprint explícita para fundação Django antes do fluxo de negócio.

### 4. Design system com nome divergente

O texto cita:

```text
design_system/refs/design-system.html
```

O repositório contém:

```text
design_system/refs/design_system.html
```

Impacto: agentes podem procurar o arquivo errado.

Correção recomendada: usar `design_system/refs/design_system.html` como referência real ou renomear o arquivo em uma tarefa controlada.

### 5. "Sem testes" pode ser interpretado de forma perigosa

A restrição correta é não criar suíte de testes automatizados como entregável do MVP. Isso não elimina verificação.

Impacto: sem DoP manual, agentes podem entregar código que não passa nem em `manage.py check`.

Correção recomendada: cada sprint deve ter Definition of Done com comandos manuais:

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
```

Quando houver Node.js:

```bash
npm test
```

Somente se a suíte já existir no `wa_service/`.

### 6. Limite de envio ambíguo

O PRD diz "até 10 ofertas por execução", mas o `orchestrator.py` seleciona um lote por marketplace e soma Mercado Livre + Amazon.

Impacto: pode enviar até 20 ofertas se `batch_size=10` for aplicado por marketplace.

Correção recomendada: o limite do MVP deve ser global por ciclo. Se houver balanceamento por marketplace, ele deve caber dentro do total de 10.

### 7. Janela de silêncio precisa bloquear distribuição, não apenas scheduler

A regra de produto diz que 00:00-06:00 BRT deve bloquear qualquer distribuição.

Impacto: um ciclo iniciado antes de 00:00 poderia continuar enviando durante a janela proibida.

Correção recomendada: validar janela antes do ciclo e antes de cada envio.

### 8. Links de afiliado ainda não são uma integração garantida

O modelo de negócio depende de afiliados, mas o MVP pode não ter geração oficial de links para todos os marketplaces.

Impacto: risco de enviar links sem monetização e medir sucesso incorretamente.

Correção recomendada: criar configuração explícita `ALLOW_ORIGINAL_LINK_WHEN_AFFILIATE_MISSING`. O padrão recomendado para MVP local pode ser `true`, desde que a limitação fique clara.

### 9. WhatsApp tem risco operacional maior que o PRD sugere

Automação via Baileys pode perder sessão, falhar por QR/login, sofrer rate limit ou bloquear conta.

Impacto: o principal canal do MVP pode parar sem erro de código Django.

Correção recomendada: tratar estado de sessão como pré-condição operacional e criar checklist manual de WhatsApp antes de cada ciclo real.

### 10. README legado contradiz o produto alvo

O README fala em GitHub Actions, Vercel e `ofertas.json`, enquanto o PRD determina execução local, Django, SQLite e WhatsApp.

Impacto: documentação atual induz decisões contrárias ao PRD.

Correção recomendada: sprint final do MVP deve atualizar README e documentação operacional.

## Decisões Recomendadas

- O MVP deve priorizar estabilidade local sobre painel customizado.
- O limite de 10 ofertas deve ser global por ciclo.
- `Delivery` deve substituir `SentOffer` como nome canônico se o código já caminhar nessa direção.
- `SocialChannel` deve existir desde o MVP para permitir `UNIQUE (offer_id, social_channel_id)`.
- O Django Admin é suficiente para operação inicial.
- `dry_run` é obrigatório antes de qualquer envio real.
- A janela 00:00-06:00 BRT deve ser validada também no serviço de distribuição.

## Lacunas que Devem Virar Backlog

- Política de retry por tipo de erro.
- Blacklist de termos e score mínimo.
- Contrato formal do `wa_service`.
- Estratégia de afiliado por marketplace.
- Histórico de preço.
- Painel customizado com design system.
- Observabilidade mínima por arquivo de log local ignorado pelo git.

## Critério de Pronto Para Iniciar Implementação

Antes de agentes implementarem o MVP, o PO deve validar:

- O banco oficial será `data/descontos_bot.db`.
- O módulo Django oficial será `core.settings`.
- O limite de 10 ofertas é global por ciclo.
- O arquivo de design system real é `design_system/refs/design_system.html`.
- Não haverá Docker nem nova suíte automatizada no MVP.
- O fluxo WhatsApp pode operar em `dry_run` até a sessão estar validada.

