#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/marce/Documents/Projetos/descontos.bot
IMAGE_GEN="$HOME/.codex/skills/.system/imagegen/scripts/image_gen.py"
PY=.venv/bin/python

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY não está setado. Configure a chave no ambiente e rode novamente." >&2
  exit 2
fi

mkdir -p media/instagram/stories tmp/imagegen

$PY "$IMAGE_GEN" edit \
  --model gpt-image-2 \
  --image resources/avatar_1080px.png \
  --quality high \
  --size 1024x1536 \
  --out media/instagram/stories/telegram_channel_promo_gpt2.png \
  --force \
  --use-case ads-marketing \
  --style "polished social media campaign poster, crisp vector-like 3D/illustration hybrid, high contrast, premium tech/deals brand" \
  --composition "9:16 vertical, central robot mascot, glowing Telegram/chat/deal visual cues, strong CTA area at bottom, mobile-first readability" \
  --palette "#0D0F14, #161A22, #1E2330, neon cyan #00C9B1, yellow #FFE14D, white #F4F7FF, subtle Telegram blue accent only as secondary" \
  --text "Entre no canal do Telegram | Link na bio!" \
  --constraints "text must be exactly correct in Portuguese; no spelling changes; no fake QR code; no watermark; preserve descontos.bot visual identity and mascot feel" \
  --negative "spammy ALL CAPS, clutter, too many emojis, wrong text, broken typography, extra brand names" \
  --prompt "Create a premium vertical Instagram Story graphic promoting the descontos.bot Telegram channel, using the provided robot mascot as brand reference. Invite people to enter the free Telegram channel for monitored deals."

$PY "$IMAGE_GEN" edit \
  --model gpt-image-2 \
  --image resources/avatar_1080px.png \
  --image tmp/imagegen/offer_8347.webp \
  --quality high \
  --size 1024x1536 \
  --out media/instagram/stories/offer_8347_groups_channel_gpt2.png \
  --force \
  --use-case ads-marketing \
  --style "high-conversion social media offer poster, clean tech/deals aesthetic, product-first layout with brand mascot supporting" \
  --composition "9:16 vertical, product image prominent in center, discount badge visible, price block high contrast, mascot/brand element, bottom CTA inviting people to join groups/channel" \
  --palette "#0D0F14, #161A22, #1E2330, neon cyan #00C9B1, yellow #FFE14D, white #F4F7FF, red/yellow discount accent allowed" \
  --text "77% OFF | R$ 113,00 | Whey Dark Lab | Grupos e canal | Link na bio!" \
  --constraints "text must be exactly correct; no invented prices; use the provided whey product image; do not imply medical claims; no fake QR code; no watermark; keep product and brand readable" \
  --negative "clutter, misspelled Portuguese, fake marketplace logos, exaggerated claims, unsafe nutrition claims, too many emojis" \
  --prompt "Create a premium vertical Instagram Story graphic for a deal already posted today in descontos.bot groups. Feature Whey Protein Concentrado 100% 900g Refil Dark Lab Sabor Chocolate from Mercado Livre with price R$ 113,00 and 77% OFF, while promoting both the WhatsApp group and Telegram channel."

echo "Generated:"
echo "media/instagram/stories/telegram_channel_promo_gpt2.png"
echo "media/instagram/stories/offer_8347_groups_channel_gpt2.png"
