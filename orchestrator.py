# -*- coding: utf-8 -*-
"""
Orquestrador do descontos.bot
==============================
1. Scraping ML + Amazon → SQLite.
2. Seleciona lote do banco, evitando reenvios.
3. Gera TXT via WhatsAppPostGenerator.
4. Envia via wa_service (handshake antes do disparo).
5. Dorme e repete.
"""

import os
import sys
import logging
import random
import time
from pathlib import Path

import requests

# ── Bootstrap Django ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()
# ─────────────────────────────────────────────────────────────────────────────

from django.core.management import call_command

from apps.curation.services.selector import select_batch
from apps.curation.services.whatsapp import WhatsAppPostGenerator
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.whatsapp_client import WhatsAppClient
from apps.offers.models import Offer
from apps.panel.models import Setting

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger('Orquestrador')

BATCH_SIZE         = 10
SCRAPE_EVERY       = 3      # a cada N ciclos roda scraping
MIN_SLEEP_MINUTES  = 90
MAX_SLEEP_MINUTES  = 180

WA_DIR = BASE_DIR / 'data' / 'posts' / 'wa'


def _int_setting(key: str, default: int) -> int:
    val = Setting.objects.filter(key=key).values_list('value', flat=True).first()
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


class Orquestrador:
    def __init__(self, skip_first_scrape: bool = False, dry_run: bool = False):
        self.ciclo = 0
        self.skip_first_scrape = skip_first_scrape
        self.dry_run = dry_run
        self._wa_ready = False  # cache do handshake do wa-service entre ciclos

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _scrape(self):
        log.info('==> Realizando raspagem de novas ofertas...')
        for code in ('mercadolivre', 'amazon'):
            log.info('🤖 Scraper %s iniciado.', code)
            try:
                call_command('scrape_marketplace', code=code)
            except Exception as exc:
                log.error('Erro scraping %s: %s', code, exc)

        # Resumo do banco após scraping
        total_ativas = Offer.objects.filter(is_active=True).count()
        log.info('💾 Banco SQLite: %d ofertas ativas no total.', total_ativas)

    # ── Despacho ──────────────────────────────────────────────────────────────

    def _baixar_imagem_produto(self, offer, dest_dir: Path) -> Path | None:
        """Baixa a imagem do produto e salva em dest_dir. Retorna o Path ou None."""
        img_url = offer.image_url or ''
        if not img_url:
            return None
        safe_id = (offer.external_id or 'oferta').replace('/', '_')
        ext = img_url.split('?')[0].rsplit('.', 1)[-1].lower()
        if ext not in {'jpg', 'jpeg', 'png', 'webp'}:
            ext = 'jpg'
        dest = dest_dir / f'{safe_id}_produto.{ext}'
        if dest.exists():
            return dest
        try:
            resp = requests.get(img_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return dest
        except Exception as exc:
            log.warning('Não foi possível baixar imagem de %s: %s', offer.external_id, exc)
            return None

    def _ensure_wa_connected(self, wa_client: WhatsAppClient) -> bool:
        """Verifica que o wa-service está acessível e conectado ao WhatsApp."""
        if self._wa_ready or self.dry_run:
            return True
        try:
            wa_client.start()
            wa_client.wait_for_login()
            self._wa_ready = True
            return True
        except Exception as exc:
            log.error('Falha no handshake com wa-service: %s', exc)
            return False

    def _dispatch(self):
        try:
            wa_channel = SocialChannel.objects.get(code='whatsapp_main', is_enabled=True)
        except SocialChannel.DoesNotExist:
            log.error('Canal whatsapp_main não encontrado. Execute: python manage.py seed_channels')
            return

        batch_size = _int_setting('batch_size', BATCH_SIZE)

        # Seleciona separadamente por marketplace, respeitando todas as regras
        # (já enviado, janela 24h, desconto mínimo) — ranking é por marketplace
        ml_offers     = select_batch(wa_channel.code, batch_size, marketplace_code='mercadolivre')
        amazon_offers = select_batch(wa_channel.code, batch_size, marketplace_code='amazon')
        offers = list(ml_offers) + list(amazon_offers)

        # Contagem de disponíveis por marketplace (ignorando o limite do batch)
        delivered_ids = Delivery.objects.filter(
            social_channel=wa_channel, delivery_status='sent',
        ).values_list('offer_id', flat=True)
        disp_ml = (
            Offer.objects.filter(is_active=True, discount_pct__gte=5, marketplace__code='mercadolivre')
            .exclude(id__in=delivered_ids).count()
        )
        disp_az = (
            Offer.objects.filter(is_active=True, discount_pct__gte=5, marketplace__code='amazon')
            .exclude(id__in=delivered_ids).count()
        )
        log.info(
            'ML: %d disponíveis → %d no lote | Amazon: %d disponíveis → %d no lote',
            disp_ml, len(ml_offers), disp_az, len(amazon_offers),
        )

        if not offers:
            log.warning('⚠️  Nenhuma oferta nova disponível para postar neste momento.')
            return

        # Top 3 de cada marketplace
        if ml_offers:
            log.info('🏆 Top 3 Mercado Livre:')
            for i, o in enumerate(ml_offers[:3], 1):
                log.info(
                    '  %d. %s — %d%% OFF — R$ %.2f',
                    i, o.title[:50], o.discount_pct, o.current_price,
                )
        if amazon_offers:
            log.info('🏆 Top 3 Amazon:')
            for i, o in enumerate(amazon_offers[:3], 1):
                log.info(
                    '  %d. %s — %d%% OFF — R$ %.2f',
                    i, o.title[:50], o.discount_pct, o.current_price,
                )

        # Geração de mídia: TXT + download da imagem do produto
        WA_DIR.mkdir(parents=True, exist_ok=True)
        wa_gen = WhatsAppPostGenerator()
        items = []
        for offer in offers:
            txt_path = wa_gen.save(offer)
            img_path = self._baixar_imagem_produto(offer, WA_DIR)
            if not img_path or not txt_path.exists():
                log.warning(
                    'Oferta %s ignorada: falha ao gerar/baixar mídia.', offer.external_id,
                )
                continue
            items.append({
                'offer': offer,
                'text_path': str(txt_path.absolute()),
                'image_path': str(img_path.absolute()),
            })

        if not items:
            log.warning('Nenhum item com mídia válida para envio.')
            return

        # Handshake com wa-service antes de tentar enviar
        wa_client = WhatsAppClient(wa_channel, dry_run=self.dry_run)
        if not self.dry_run and not self._ensure_wa_connected(wa_client):
            log.error('Abortando despacho: wa-service indisponível.')
            return

        log.info('📤 Disparando lote (%d ofertas) no alvo: %s', len(items), wa_channel.target)
        result = wa_client.send_batch(items)
        log.info(
            '✅ Lote finalizado: %d enviados, %d ignorados, %d erros.',
            result.get('sent', 0),
            result.get('skipped', 0),
            result.get('errors', 0),
        )

        # Total persistido no banco
        total_sent = Delivery.objects.filter(
            social_channel=wa_channel, delivery_status='sent',
        ).count()
        log.info('🗂️  Histórico no banco: %d ofertas já enviadas.', total_sent)

    # ── Loop principal ────────────────────────────────────────────────────────

    def run(self):
        log.info('🚀 Iniciando Orquestrador Contínuo — descontos.bot (Ctrl+C para sair)')
        if self.dry_run:
            log.info('[dry-run] Nenhum envio real será feito.')

        while True:
            self.ciclo += 1
            log.info('====================================')
            log.info('   INICIANDO CICLO #%d', self.ciclo)
            log.info('====================================')

            deve_scrape = (
                (self.ciclo == 1 and not self.skip_first_scrape)
                or (self.ciclo > 1 and self.ciclo % SCRAPE_EVERY == 0)
            )

            if deve_scrape:
                self._scrape()
            else:
                log.info('=> Pulando scraping neste ciclo (regra: 1 a cada %d).', SCRAPE_EVERY)

            self._dispatch()

            min_min = _int_setting('cycle_min_minutes', MIN_SLEEP_MINUTES)
            max_min = _int_setting('cycle_max_minutes', MAX_SLEEP_MINUTES)
            minutos = int(random.uniform(min_min, max_min))
            log.info('😴 Fim do Ciclo #%d. Dormindo por %d minutos...', self.ciclo, minutos)
            time.sleep(minutos * 60)


if __name__ == '__main__':
    skip = '--no-scrape' in sys.argv
    dry  = '--dry-run'   in sys.argv
    app = Orquestrador(skip_first_scrape=skip, dry_run=dry)
    try:
        app.run()
    except KeyboardInterrupt:
        log.info('Encerrando Orquestrador pelo usuário (Ctrl+C).')
