"""Comando manual do radar de mercado (Sprint 6 / Tarefa 6.1, achado P7).

Roda a coleta do ranking de vendas Shopee do dia e imprime o `escore_venda`
por categoria/produto. Não publica nada, não persiste nada em banco (ver
docstring de `apps.marketplaces.services.radar_mercado`) e não instala
nenhuma unit systemd — a decisão de agendar isso 1x/dia (timer/cron) fica
para o dono depois. Serve hoje para inspeção manual; o próprio ciclo de
curadoria (`prepare_ai_curation_batch`) já chama `collect_radar_mercado()`
internamente a cada execução para alimentar `quality_score` e o payload da
IA, então este comando não é pré-requisito funcional daquele fluxo.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.marketplaces.services.radar_mercado import collect_radar_mercado


class Command(BaseCommand):
    help = (
        'Coleta o radar de mercado (ranking de vendas Shopee do dia, best-effort) e '
        'imprime o escore_venda por categoria/produto. Gate: exige SHOPEE_AFFILIATE_ENABLED=true '
        '(desligado por padrão em produção); com a flag off, imprime resultado neutro sem chamar a API.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--top-n-categories', type=int, default=None, help='Quantas categorias consultar (padrão do módulo).')
        parser.add_argument('--limit-per-category', type=int, default=None, help='Itens por categoria (padrão do módulo).')
        parser.add_argument('--json', action='store_true', help='Imprime o resultado bruto como JSON.')

    def handle(self, *args, **options):
        kwargs = {}
        if options['top_n_categories']:
            kwargs['top_n_categories'] = options['top_n_categories']
        if options['limit_per_category']:
            kwargs['limit_per_category'] = options['limit_per_category']

        result = collect_radar_mercado(**kwargs)

        if options['json']:
            self.stdout.write(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            return

        if not result.enabled:
            self.stdout.write(self.style.WARNING(f'Radar desligado: {result.limitations}'))
            return

        self.stdout.write(f'Radar de mercado coletado em {result.collected_at}')
        self.stdout.write(f'Categorias cobertas: {", ".join(result.categories_covered) or "-"}')
        self.stdout.write(f'Amostra: {result.sample_size} itens')
        self.stdout.write('')
        self.stdout.write('Escore de venda por categoria (0..1, maior = mais vendido no dia):')
        for code, score in sorted(result.category_scores.items(), key=lambda item: -item[1]):
            self.stdout.write(f'  {code:30} {score:.4f}')
        self.stdout.write('')
        self.stdout.write('Top produtos:')
        for name, score in sorted(result.product_scores.items(), key=lambda item: -item[1])[:10]:
            self.stdout.write(f'  {score:.4f}  {name}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'Limitações: {result.limitations}'))
