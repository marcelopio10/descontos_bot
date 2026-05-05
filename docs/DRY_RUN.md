# Dry Run — descontos.bot

Use o `dry_run` para revisar a curadoria e as mensagens antes de qualquer envio real no WhatsApp.

## Preparação

Execute os seeds iniciais para garantir canal e configurações operacionais:

```bash
python3 manage.py seed_initial_data --target "Nome exato do grupo WhatsApp"
```

Se as ofertas já foram coletadas, rode a prévia:

```bash
python3 manage.py run_bot --dry-run --once
```

## Comportamento

- Seleciona apenas ofertas ativas, com marketplace ativo, título, URL, preço atual e desconto mínimo.
- Remove ofertas que já têm `Delivery` com status `sent` no canal escolhido.
- Ordena por maior desconto.
- Aplica `offer_limit_per_marketplace` e `offer_limit_global`.
- Monta mensagens em pt-BR seguindo o padrão do `WhatsAppPostGenerator` em `post_generator.py`.
- Usa `affiliate_url` quando existir; caso contrário, usa `product_url`.
- Não chama o `wa_service/`.
- Não grava `Delivery`, para não bloquear um envio real futuro pela regra única de oferta por canal.

O formato de mensagem inclui:

```text
📦 *Produto*

🔥 *ALERTA DO BOT* 🔥
━━━━━━━━━━━━━━━━━━━━━

💰 ~De R$ 199,90~
✅ *Por apenas R$ 129,90*
🏷️ *35% OFF*

🛒 Compre aqui 👇
https://...

⏰ Oferta por tempo limitado!
━━━━━━━━━━━━━━━━━━━━━
🤖 @descontos.bot
```

## Configurações

As chaves ficam em `Setting` e podem ser criadas ou atualizadas com:

```bash
python3 manage.py seed_settings
```

Chaves usadas na Sprint 3:

- `offer_limit_global`: limite total por ciclo. Valor inicial: `20`.
- `offer_limit_per_marketplace`: limite por marketplace no ciclo. Valor inicial: `10`.
- `min_discount_percentage`: desconto mínimo para seleção. Valor inicial: `20`.

## Canal

O canal padrão é `whatsapp_principal`. Para usar outro canal habilitado:

```bash
python3 manage.py run_bot --dry-run --once --channel outro_codigo
```

## Envio real em ciclo único

Antes de enviar mensagens reais, inicie o serviço WhatsApp em outro terminal:

```bash
cd wa_service
npm run dev
```

Confirme que o serviço está conectado:

```bash
curl http://127.0.0.1:8787/status
```

Com autorização do PO, rode um ciclo real único:

```bash
python3 manage.py run_bot --once
```

## Scheduler local

Para rodar continuamente em `dry_run`:

```bash
python3 manage.py run_bot --dry-run
```

O intervalo entre ciclos é randômico e usa as configurações:

- `cycle_min_minutes`: padrão `90`.
- `cycle_max_minutes`: padrão `180`.

Para conferir o cálculo do próximo intervalo sem aguardar:

```bash
python3 manage.py run_bot --dry-run --once --skip-scraping --show-next-interval
```

Comportamento esperado:

- Chama `POST /send-message` no `wa_service/` para cada oferta selecionada.
- Registra `Delivery` como `sent`, `failed` ou `skipped`.
- Mantém deduplicação por oferta e canal.
- Não marca oferta como enviada quando o WhatsApp falha ou está desconectado.
- Bloqueia distribuição entre 00:00 e 06:00 BRT antes de cada envio.

Para parar o serviço, use `Ctrl+C` no terminal onde `npm run dev` está rodando.
