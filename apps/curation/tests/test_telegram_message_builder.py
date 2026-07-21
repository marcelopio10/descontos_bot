from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.message_builder import _select_badge_variant
from apps.curation.services.telegram_message_builder import build_telegram_payload
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class TelegramBadgeIntegrationTests(TestCase):
    """Tarefa 5.3: o badge do Telegram usa a MESMA seleção/índice do WhatsApp
    (`_select_badge_variant`), só trocando o negrito Markdown por HTML `<b>`.
    """

    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='Telegram Main',
            code='telegram_main',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='-100123456',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )

    def _make_offer(self, offer_hash: str, discount_pct: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=offer_hash,
            title='Fone Bluetooth X',
            normalized_title='fone bluetooth x',
            offer_hash=offer_hash,
            slug=f'fone-{offer_hash}',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal(discount_pct),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_caption_uses_html_bold_badge_matching_whatsapp_selection(self):
        offer = self._make_offer('tg-badge-1', '18.00')
        payload = build_telegram_payload(offer, self.channel)
        lead, label, trail = _select_badge_variant(18, offer.id)
        self.assertIn(f'{lead} <b>{label}</b> {trail}', payload.caption)
        self.assertNotIn(f'*{label}*', payload.caption)

    def test_same_offer_rendered_twice_yields_the_same_caption(self):
        offer = self._make_offer('tg-badge-2', '55.00')
        first = build_telegram_payload(offer, self.channel)
        second = build_telegram_payload(offer, self.channel)
        self.assertEqual(first.caption, second.caption)
