# GPT Image 2 prompts — Instagram Stories descontos.bot

Bloqueio atual: `OPENAI_API_KEY` não está setado no ambiente. Quando estiver disponível, use `.venv/bin/python` com o CLI abaixo.

## 1) Divulgação canal Telegram

Output: `media/instagram/stories/telegram_channel_promo_gpt2.png`
Reference image: `resources/avatar_1080px.png`

Prompt:

Use case: ads-marketing
Asset type: Instagram Story 9:16 promotional post
Primary request: Create a premium vertical Instagram Story graphic promoting the descontos.bot Telegram channel, using the provided robot mascot as brand reference. The design must invite people to enter the free Telegram channel for monitored deals.
Subject: descontos.bot friendly robot mascot, Telegram channel promotion, deal alerts, shopping savings.
Style/medium: polished social media campaign poster, crisp vector-like 3D/illustration hybrid, high contrast, premium tech/deals brand.
Composition/framing: 9:16 vertical, central robot mascot, glowing Telegram/chat/deal visual cues, strong CTA area at bottom, mobile-first readability.
Color palette: official descontos.bot dark theme: #0D0F14, #161A22, #1E2330, neon cyan #00C9B1, yellow #FFE14D, white #F4F7FF, subtle Telegram blue accent only as secondary.
Text (verbatim): "Entre no canal do Telegram" and "Link na bio!"
Constraints: text must be exactly correct in Portuguese, no spelling changes, no extra exclamation marks beyond "Link na bio!", no fake QR code, no watermark, no unrelated logos. Preserve brand identity and mascot feel.
Avoid: spammy ALL CAPS, clutter, too many emojis, wrong text, broken typography, extra brand names.

## 2) Oferta postada hoje + divulgação grupos/canal

Offer selected from today's sent group posts:
- delivery_id: 11700
- offer_id: 8347
- title: Whey Protein Concentrado 100% 900g Refil Dark Lab Sabor Chocolate
- marketplace: Mercado Livre
- current_price: R$ 113,00
- original_price: R$ 499,00
- discount: 77% OFF
- reference image: `tmp/imagegen/offer_8347.webp`
- mascot reference: `resources/avatar_1080px.png`

Output: `media/instagram/stories/offer_8347_groups_channel_gpt2.png`

Prompt:

Use case: ads-marketing
Asset type: Instagram Story 9:16 offer repost + community promotion
Primary request: Create a premium vertical Instagram Story graphic for a deal that was already posted today in descontos.bot groups. Feature the product offer visually and promote both the WhatsApp group and Telegram channel.
Subject: Whey Protein Concentrado 100% 900g Refil Dark Lab Sabor Chocolate deal, Mercado Livre, discounts community, descontos.bot robot mascot.
Style/medium: high-conversion social media offer poster, clean tech/deals aesthetic, product-first layout with brand mascot supporting.
Composition/framing: product image prominent in the center, discount badge visible, price block high contrast, mascot/brand element, bottom CTA inviting people to join groups/channel. Keep enough spacing for mobile readability.
Color palette: official descontos.bot dark theme: #0D0F14, #161A22, #1E2330, neon cyan #00C9B1, yellow #FFE14D, white #F4F7FF, red/yellow discount accent allowed.
Text (verbatim): "77% OFF", "R$ 113,00", "Whey Dark Lab", "Grupos e canal", "Link na bio!"
Constraints: text must be exactly correct; no invented prices; do not use another product; do not imply medical claims; no fake QR code; no watermark; keep product and brand readable.
Avoid: clutter, misspelled Portuguese, fake marketplace logos, exaggerated claims, unsafe nutrition claims, too many emojis.
