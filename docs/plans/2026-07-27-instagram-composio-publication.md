# Instagram Composio Publication Implementation Plan

> Aprovado por Marcelo em 2026-07-27. Executar sem apagar ou resetar alterações locais pré-existentes.

**Goal:** substituir o publisher Instagram atual por um fluxo seguro Feed/Story via Composio SDK, fixado à connected account do descontos.bot, com preflight de identidade, reconciliação, idempotência, dry-run e comando operacional.

**Architecture:** manter a geração atual de `InstagramPost` e os formatos Feed/Story. Adaptar `apps/social_posts/services/composio_publisher.py` para usar o SDK Python do Composio com `connected_account_id`, validar a conta antes de criar containers, publicar o asset local, consultar a mídia publicada e só então marcar o post como `posted`. Carrossel fica fora da primeira entrega. O handoff manual permanece como fallback, especialmente porque a API não cria Link Sticker de Story.

**Tech Stack:** Django, SQLite, Pillow, Composio Python SDK, Instagram Graph actions via Composio, pytest/unittest Django.

## Escopo aprovado

- Feed e Story via Composio.
- Preflight `ACTIVE` + `INSTAGRAM_GET_USER_INFO` + username esperado.
- Upload de arquivo local com `file_upload_dirs` restrito ao diretório do projeto.
- Criação de container, publicação e consulta `INSTAGRAM_GET_IG_MEDIA`.
- Persistência de container ID, media ID, permalink, tentativas, erro e recibo.
- Dry-run e confirmação explícita para publicação real.
- Idempotência e bloqueio de resultado externo desconhecido.
- Carrossel fora desta fase.
- Nenhum segredo em código, documentação, logs ou Git.

## Estado inicial conhecido

- Checkout `main` divergente de `origin/main` e com alterações locais não relacionadas; não fazer reset, clean, commit ou push sem autorização explícita.
- `apps/social_posts/services/composio_publisher.py` usa atualmente CLI, `INSTAGRAM_USER_ID` fixo e atualiza diretamente para `posted` após publish.
- `InstagramPost` já possui `instagram_media_id`, `published_error`, `posted_at`, `asset_paths`, `caption` e `sticker_target_url`.
- O padrão de referência está em `/mnt/c/Users/marce/Documents/Projetos/pioexplica/src/pioexplica/instagram_publish.py`.

## Tasks

### Task 1 — Baseline e alinhamento do repositório

- Reconfirmar `git status --short --branch`, `git diff --check` e o conjunto de mudanças locais.
- Ler settings, requirements, migrations, Admin, comandos e testes atuais.
- Classificar arquivos gerados/locais e não sobrescrever mudanças existentes.
- Registrar checkpoint sem commit automático.

### Task 2 — Configuração segura

- Adicionar somente nomes/placeholders ao `.env.example`:
  - `COMPOSIO_API_KEY`
  - `COMPOSIO_PROJECT_NAME`
  - `COMPOSIO_USER_ID`
  - `COMPOSIO_INSTAGRAM_ACCOUNT_ID`
  - `INSTAGRAM_EXPECTED_USERNAME`
  - `INSTAGRAM_PUBLISH_DRY_RUN`
- Carregar valores em `core/settings.py`.
- Manter compatibilidade temporária com a configuração atual somente onde não reduzir a segurança.
- Não ler, imprimir ou modificar valores secretos do `.env` sem autorização explícita.

### Task 3 — Modelo e migration de auditoria

- Adicionar ao `InstagramPost`, se ausentes:
  - `instagram_container_id`;
  - `instagram_permalink`;
  - `publish_attempts`;
  - `publish_state` ou equivalente explícito para `pending`, `started`, `confirmed`, `unknown`, `failed`;
  - `asset_hash`/`content_hash` quando necessário para idempotência.
- Criar migration.
- Preservar os estados existentes e compatibilidade com os 21 posts `awaiting_post`.
- Não alterar posts antigos automaticamente.

### Task 4 — Executor Composio fixado à conta

- Refatorar `apps/social_posts/services/composio_publisher.py`.
- Usar o SDK Python `Composio(...).tools.execute(...)` com `connected_account_id`.
- Limitar `file_upload_dirs` à raiz de assets do projeto.
- Manter fallback CLI somente se necessário e explicitamente documentado.
- Implementar preflight da connected account e username esperado.
- Converter assets para JPEG temporário conforme contrato do formato.
- Usar `media_type=STORIES` apenas para Story.
- Não expor a URL do Link Sticker como se a API a tivesse criado.

### Task 5 — Reconciliação e idempotência

- Registrar o container ID assim que retornado.
- Persistir a tentativa antes do efeito externo quando possível.
- Consultar `INSTAGRAM_GET_IG_MEDIA` após publicação.
- Validar username, media ID, permalink e caption.
- Só marcar `posted` após confirmação.
- Em timeout ou resposta ambígua, marcar `unknown`/reconciliação e bloquear retry automático.
- Criar recibo persistente com post, conta, formato, IDs, permalink, hash e timestamp.
- Retornar recibo existente quando o post já estiver confirmado.

### Task 6 — Comando operacional e Admin

- Criar/ajustar `check_instagram_composio` para preflight sem publicar.
- Criar/ajustar `publish_instagram_post --post-id <id> --dry-run`.
- Exigir confirmação explícita para publicação real.
- Permitir publicação individual no Admin.
- Bloquear publicação de post já confirmado.
- Exibir erro, media ID, permalink e estado de reconciliação.

### Task 7 — Testes

- Testar configuração ausente e conta divergente.
- Testar preflight ativo/inativo.
- Testar payload Feed e Story.
- Testar passagem de `connected_account_id` e upload local do SDK.
- Testar dry-run sem alterar status para `posted`.
- Testar publicação confirmada atualizando IDs, permalink, status e data.
- Testar erro/timeout sem marcar `posted`.
- Testar idempotência do recibo.
- Testar bloqueio de carrossel nesta fase.
- Usar mocks para Composio; nenhum teste deve publicar externamente.

### Task 8 — Documentação e operação

- Atualizar `21 - Instagram Operacional.md` e documentação técnica do repositório.
- Documentar criação da connected account e preflight, sem valores secretos.
- Documentar que Stories publicados via API continuam sem Link Sticker automático.
- Documentar fallback manual via Telegram/Admin.
- Documentar sequência segura de produção.

### Task 9 — Validação real controlada

- Executar `manage.py check`, migration check, testes focados, compliance e `git diff --check`.
- Solicitar a Marcelo somente os dados necessários para o preflight real, sem pedir token se o SDK já usar a autenticação local configurada.
- Rodar preflight real e confirmar o username esperado.
- Publicar um único Feed de teste com confirmação explícita.
- Reconciliar a mídia e conferir permalink no Instagram.
- Publicar um único Story de teste, registrando a limitação do Link Sticker.
- Só depois avaliar habilitação automática; manter `INSTAGRAM_AUTO_PUBLISH=false` até aprovação operacional.

## Gates de aceitação

- Conta Composio ativa e username correto antes de qualquer publicação.
- Dry-run não cria container nem altera `posted`.
- Publicação real individual produz media ID e permalink verificáveis.
- `posted` só aparece após reconciliação.
- Timeout/resultado desconhecido não gera retry cego nem duplicata.
- Feed e Story funcionam; carrossel permanece bloqueado.
- Nenhum segredo aparece no diff, logs ou documentação.
- Testes focados e gates básicos passam com saída real.

## Rollback

- Desligar `INSTAGRAM_AUTO_PUBLISH`.
- Usar o handoff Telegram/Admin existente.
- Manter migrations compatíveis; não apagar recibos nem reescrever estados externos.
- Não resetar o checkout para desfazer alterações locais sem decisão explícita.
