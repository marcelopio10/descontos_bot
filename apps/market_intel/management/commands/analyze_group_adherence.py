import json

from django.core.management.base import BaseCommand

from apps.market_intel.services.adherence import build_adherence, radar_latency


class Command(BaseCommand):
    help = (
        'Cruza o que foi enviado ao canal com o que os grupos observados publicaram: '
        'taxa de eco, cobertura das ofertas de consenso e atraso em relação a eles.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--channel', default='whatsapp_principal')
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        relatorio = build_adherence(days=options['days'], channel_code=options['channel'])
        latencia = radar_latency(channel_code=options['channel'])

        if options['json']:
            self.stdout.write(json.dumps(
                {**relatorio.as_dict(), 'latencia_do_radar': latencia},
                ensure_ascii=False, indent=2,
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Aderência aos grupos — {relatorio.canal}, {relatorio.janela_dias} dia(s)'
        ))
        self.stdout.write(
            f'  {relatorio.envios} envios contra {relatorio.mensagens_observadas} mensagens observadas'
        )
        self.stdout.write(
            f'  eco nos grupos: {relatorio.envios_com_eco} ({relatorio.taxa_eco}% no critério '
            f'estrito, {relatorio.taxa_eco_de_familia}% contando só o tipo de produto) | '
            f'só nós: {relatorio.envios_exclusivos}'
        )
        lag = relatorio.lag_mediano
        self.stdout.write(f'  atraso mediano em relação ao primeiro grupo: {lag}h' if lag is not None
                          else '  atraso mediano: sem dado')
        self.stdout.write(
            f'  ofertas com {relatorio.ofertas_consenso_forte and "3+" or "3+"} grupos: '
            f'{relatorio.ofertas_consenso_forte} | publicamos {relatorio.consenso_forte_publicado} '
            f'({relatorio.taxa_cobertura_consenso}%)'
        )

        if relatorio.por_origem:
            self.stdout.write('\n  Por origem da coleta:')
            for origem, dados in relatorio.por_origem.items():
                atraso = dados['lag_mediano_horas']
                self.stdout.write(
                    f"    {origem:20} {dados['envios']:>4} envios | eco {dados['taxa_de_eco_pct']:>5}%"
                    f" | atraso {f'{atraso}h' if atraso is not None else '—'}"
                )

        if latencia['publicados_pelo_radar']:
            self.stdout.write(
                f"\n  Latência do radar (par exato mensagem→anúncio, "
                f"{latencia['publicados_pelo_radar']} ofertas):"
            )
            self.stdout.write(
                f"    mensagem do grupo até nosso envio: mediana "
                f"{latencia['latencia_mediana_horas']}h "
                f"(de {latencia['latencia_minima_horas']}h a {latencia['latencia_maxima_horas']}h)"
            )
            self.stdout.write(
                f"    desses, até resolver o link: {latencia['ate_resolver_mediana_horas']}h | "
                f"{latencia['ja_estavam_no_canal']} anúncios já tinham saído antes do radar"
            )

        if relatorio.lacunas:
            self.stdout.write('\n  Maiores lacunas (muito grupo, nós zero):')
            for lacuna in relatorio.lacunas:
                self.stdout.write(
                    f"    {lacuna['grupos']} grupos | {lacuna['familia'][:18]:18} "
                    f"{lacuna['faixa_preco']:>10} | {lacuna['exemplo']}"
                )

        if relatorio.exclusivos:
            self.stdout.write('\n  Amostra do que só nós publicamos:')
            for item in relatorio.exclusivos[:10]:
                self.stdout.write(
                    f"    R$ {item['preco']:>8.2f} | {item['origem'][:16]:16} | {item['titulo']}"
                )
