import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.services.mercadolivre_api_client import (
    MercadoLivreApiError,
    MercadoLivreApiClient,
)
from apps.marketplaces.services.mercadolivre_auth import (
    MercadoLivreAuthError,
    validate_api_configuration,
)

ALLOWED_CONFIGURATION_FIELDS = (
    'ML_API_BASE_URL',
    'ML_API_SITE_ID',
    'ML_API_ACCESS_TOKEN',
    'ML_API_CLIENT_ID',
    'ML_API_CLIENT_SECRET',
    'ML_API_REFRESH_TOKEN',
)
ML_ITEM_ID_RE = re.compile(r'^MLB[0-9]+$')


def _safe_auth_error_message(error: MercadoLivreAuthError) -> str:
    raw_fields = error.missing_fields
    if not isinstance(raw_fields, (tuple, list)):
        return 'Autenticação/configuração da API ML recusada.'
    if not all(isinstance(field, str) for field in raw_fields):
        return 'Autenticação/configuração da API ML recusada.'
    fields = tuple(raw_fields)
    if (
        error.code == 'configuration_incomplete'
        and fields
        and len(fields) == len(set(fields))
        and all(field in ALLOWED_CONFIGURATION_FIELDS for field in fields)
    ):
        ordered_fields = [
            field for field in ALLOWED_CONFIGURATION_FIELDS if field in fields
        ]
        return 'Configuração da API ML incompleta: ' + ', '.join(ordered_fields) + '.'
    if error.code == 'configuration_invalid':
        return 'Configuração da API ML inválida.'
    return 'Autenticação/configuração da API ML recusada.'


def _validate_probe_body(body, requested_limit: int) -> tuple[int | None, int, str]:
    try:
        if not isinstance(body, dict):
            raise CommandError('API do Mercado Livre retornou formato inesperado.')
        paging = body.get('paging')
        results = body.get('results')
        if not isinstance(paging, dict):
            raise CommandError('API do Mercado Livre retornou paging inválido.')
        if not isinstance(results, list):
            raise CommandError('API do Mercado Livre retornou results inválido.')
        required_paging_fields = ('total', 'offset', 'limit')
        missing_paging_fields = [
            name for name in required_paging_fields if name not in paging
        ]
        if missing_paging_fields:
            raise CommandError(
                'API do Mercado Livre retornou paging incompleto: '
                f'{", ".join(missing_paging_fields)}.',
            )
        for field_name in required_paging_fields:
            value = paging[field_name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CommandError(
                    f'API do Mercado Livre retornou paging.{field_name} inválido.',
                )
        if paging['limit'] == 0:
            raise CommandError('API do Mercado Livre retornou paging.limit inválido.')
        if paging['offset'] != 0:
            raise CommandError('API do Mercado Livre retornou página inicial inválida.')
        if paging['limit'] > requested_limit:
            raise CommandError('API do Mercado Livre retornou limite acima do solicitado.')
        total = paging['total']
        expected_result_count = min(total, paging['limit'])
        if len(results) != expected_result_count:
            raise CommandError('API do Mercado Livre retornou cardinalidade inconsistente.')
        if any(
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
            or not ML_ITEM_ID_RE.fullmatch(item)
            for item in results
        ):
            raise CommandError('API do Mercado Livre retornou item de results inválido.')
        if len(set(results)) != len(results):
            raise CommandError('API do Mercado Livre retornou IDs duplicados.')
        return total, len(results), ''
    except CommandError as error:
        return None, 0, str(error)
    except Exception:  # noqa: BLE001 - corpo externo fail-closed
        return None, 0, 'API do Mercado Livre retornou schema inválido.'


class Command(BaseCommand):
    help = 'Verifica a conexão somente leitura com a API pública do Mercado Livre.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1)

    def handle(self, *args, **options):
        limit = options['limit']
        if limit < 1 or limit > 10:
            raise CommandError('--limit deve ficar entre 1 e 10.')
        failure_message = None
        body = None
        try:
            validate_api_configuration()
            client = MercadoLivreApiClient()
            body = client.get(
                f'/sites/{settings.ML_API_SITE_ID}/search',
                params={'limit': limit, 'offset': 0},
            )
        except MercadoLivreAuthError as exc:
            failure_message = _safe_auth_error_message(exc)
        except MercadoLivreApiError as exc:
            status_code = exc.status_code
            status = (
                status_code
                if not isinstance(status_code, bool) and isinstance(status_code, int)
                else None
            )
            failure_message = (
                'API do Mercado Livre rejeitou o probe: '
                f'HTTP {status if status is not None else "rede"}.'
            )
        except Exception:  # noqa: BLE001 - fronteira externa fail-closed
            failure_message = 'Probe da API do Mercado Livre falhou por erro interno não detalhado.'

        if failure_message is not None:
            raise CommandError(failure_message)

        total, result_count, schema_error = _validate_probe_body(body, limit)
        if schema_error:
            raise CommandError(schema_error)
        self.stdout.write(self.style.SUCCESS(
            f'Mercado Livre API: OK; site={settings.ML_API_SITE_ID}; '
            f'resultados={result_count}; total={total}',
        ))
