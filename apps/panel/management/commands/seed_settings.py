from django.core.management.base import BaseCommand

from apps.panel.models import Setting


class Command(BaseCommand):
    help = 'Cria ou atualiza configurações operacionais iniciais.'

    def handle(self, *args, **options):
        settings = [
            {
                'key': 'batch_size',
                'value': '20',
                'description': 'Limite legado de ofertas por ciclo.',
            },
            {
                'key': 'offer_limit_global',
                'value': '20',
                'description': 'Limite global de ofertas por ciclo em dry_run e envio.',
            },
            {
                'key': 'offer_limit_per_marketplace',
                'value': '10',
                'description': 'Limite de ofertas por marketplace em cada ciclo.',
            },
            {
                'key': 'cycle_min_minutes',
                'value': '90',
                'description': 'Intervalo mínimo entre ciclos contínuos.',
            },
            {
                'key': 'cycle_max_minutes',
                'value': '180',
                'description': 'Intervalo máximo entre ciclos contínuos.',
            },
            {
                'key': 'min_discount_percentage',
                'value': '20',
                'description': 'Desconto mínimo recomendado para seleção.',
            },
            {
                'key': 'allow_original_link_when_affiliate_missing',
                'value': 'true',
                'description': 'Permite link original quando afiliado não existir.',
            },
            {
                'key': 'referral_enabled',
                'value': 'true',
                'description': 'Anexa convite de compartilhamento (hub /links) a cada N mensagens.',
            },
            {
                'key': 'referral_every_n',
                'value': '5',
                'description': 'Insere sufixo de referral quando offer.id % N == 0. Use 0 para desabilitar via cadência.',
            },
            {
                'key': 'categories_enabled',
                'value': '1',
                'description': 'Sprint 1 — quando 0, classificador de categorias não persiste.',
            },
            {
                'key': 'use_category_score',
                'value': '1',
                'description': 'Sprint 2 — quando 0, score volta ao algoritmo legado.',
            },
            {
                'key': 'min_quality_score',
                'value': '55',
                'description': 'Sprint 2 — score mínimo para publicação (threshold soft).',
            },
            {
                'key': 'priority_quality_score',
                'value': '70',
                'description': 'Sprint 2 — score que coloca a oferta em prioridade máxima.',
            },
            {
                'key': 'category_weights',
                'value': '{}',
                'description': 'Sprint 3 — override JSON {code: int 1-10} sobre Category.weight. Vazio = usa banco.',
            },
            {
                'key': 'soft_penalty_terms',
                'value': '{}',
                'description': 'Sprint 4 — JSON {term: fator 0..1} de penalidades suaves no score. Vazio = usa DEFAULT_SOFT_PENALTIES.',
            },
            {
                'key': 'category_scraping_enabled',
                'value': '0',
                'description': 'Sprint 5 — quando 1, scrapers usam category_targets em vez de scrape_daily_deals.',
            },
            {
                'key': 'exposure_quota_enabled',
                'value': '0',
                'description': 'Sprint 6 — quando 1, selector aplica Category.exposure_quota_pct por ciclo.',
            },
        ]

        for data in settings:
            setting, created = Setting.objects.update_or_create(
                key=data['key'],
                defaults=data,
            )
            action = 'criada' if created else 'atualizada'
            self.stdout.write(
                self.style.SUCCESS(
                    f'Configuração {setting.key} {action}.',
                ),
            )
