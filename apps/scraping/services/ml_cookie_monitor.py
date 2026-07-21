"""Monitor preditivo de expiração do cookie/token de sessão do Mercado Livre.

Contexto: o scraper (`scrapers.mercado_livre.MercadoLivreScraper`) já dispara
um alerta REATIVO (categoria `ml_cookie_expirado`) quando uma chamada
autenticada real à API de afiliados do ML é rejeitada com HTTP 401/403 — esse
é o sinal mais confiável de que o cookie precisa ser renovado, porque vem
direto do Mercado Livre.

Este módulo complementa o alerta reativo com uma estimativa PREDITIVA leve,
para avisar o operador *antes* do cookie quebrar em produção. Deliberadamente
não tentamos decodificar/validar o conteúdo do `ML_COOKIE`/`ML_CSRF_TOKEN` —
é um formato interno opaco do Mercado Livre, sujeito a mudar sem aviso, e
parsear isso acoplaria o scraper a um detalhe de implementação frágil. Em vez
disso, usamos duas Settings configuráveis pelo operador:

- `ml_cookie_atualizado_em` (Setting, texto ISO 8601): a última vez que o
  operador renovou o cookie manualmente no `.env`. **Precisa ser setada à
  mão** pelo operador toda vez que ele renova o cookie — não há como
  descobrir isso automaticamente.
- `ml_cookie_validade_dias_esperada` (Setting, inteiro): quantos dias o
  cookie costuma durar antes de expirar, na experiência do operador. Default
  conservador de `DEFAULT_VALIDADE_DIAS` dias — é um palpite documentado,
  não uma garantia contratual do Mercado Livre sobre TTL de sessão.

Limitação conhecida e intencional: se `ml_cookie_atualizado_em` nunca foi
setada, `dias_restantes_estimados()` retorna `None` e nenhum alerta preditivo
é disparado (comportamento seguro por ausência de dado — não inventamos uma
data de referência). Nesse caso, só o alerta reativo continua funcionando.
"""

import logging
from datetime import datetime

from django.utils import timezone

from apps.analytics.services.alertas import enviar_alerta_operador
from apps.curation.services.settings import get_integer_setting
from apps.panel.models import Setting


log = logging.getLogger(__name__)

SETTING_ATUALIZADO_EM = 'ml_cookie_atualizado_em'
SETTING_VALIDADE_DIAS = 'ml_cookie_validade_dias_esperada'

# Palpite conservador documentado — o Mercado Livre não publica o TTL real da
# sessão de afiliado. Ajustável via Setting `ml_cookie_validade_dias_esperada`
# se a experiência do operador indicar um valor mais preciso.
DEFAULT_VALIDADE_DIAS = 30

# Dispara o alerta preditivo quando faltar esta quantidade de dias ou menos
# (incluindo estimativa já vencida, i.e. dias_restantes negativo).
ALERTA_ANTECEDENCIA_DIAS = 3


def _get_atualizado_em() -> datetime | None:
    """Lê a Setting `ml_cookie_atualizado_em` e faz parse como datetime ISO 8601.

    Retorna None se a Setting não existe, está vazia, ou tem formato inválido
    (nesse último caso loga um warning — sem nunca expor o valor de
    ML_COOKIE/ML_CSRF_TOKEN, que não é lido por este módulo).
    """
    valor = Setting.objects.filter(key=SETTING_ATUALIZADO_EM).values_list('value', flat=True).first()
    if not valor:
        return None

    try:
        parsed = datetime.fromisoformat(valor.strip())
    except ValueError:
        log.warning(
            'ml_cookie_monitor.timestamp_invalido setting=%s (esperado ISO 8601)',
            SETTING_ATUALIZADO_EM,
        )
        return None

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def dias_restantes_estimados() -> int | None:
    """Estimativa de dias restantes até a expiração esperada do cookie.

    Retorna None quando não há dado suficiente (Setting `ml_cookie_atualizado_em`
    nunca foi setada pelo operador) — o caller deve tratar isso como "sem
    alerta preditivo disponível", nunca como "0 dias restantes".
    """
    atualizado_em = _get_atualizado_em()
    if atualizado_em is None:
        return None

    validade_dias = get_integer_setting(SETTING_VALIDADE_DIAS, DEFAULT_VALIDADE_DIAS)
    limite = atualizado_em + timezone.timedelta(days=validade_dias)
    delta = limite - timezone.now()
    return delta.days


def verificar_cookie_prestes_a_vencer(dias_antecedencia: int = ALERTA_ANTECEDENCIA_DIAS) -> bool:
    """Verifica a estimativa preditiva e dispara alerta se faltar pouco (ou já venceu).

    Retorna True se o alerta foi disparado, False caso contrário — incluindo o
    caso "sem dado suficiente" (`ml_cookie_atualizado_em` não configurada), que
    é uma limitação conhecida e documentada no topo do módulo, não um erro.
    """
    dias_restantes = dias_restantes_estimados()
    if dias_restantes is None:
        log.info('ml_cookie_monitor.sem_dado_preditivo setting=%s', SETTING_ATUALIZADO_EM)
        return False

    if dias_restantes > dias_antecedencia:
        return False

    log.error(
        'ml_cookie_monitor.prestes_a_vencer dias_restantes=%s dias_antecedencia=%s',
        dias_restantes, dias_antecedencia,
    )
    if dias_restantes < 0:
        mensagem = (
            f'Cookie do Mercado Livre provavelmente já venceu (estimativa: '
            f'{abs(dias_restantes)} dia(s) atrás, com base na última atualização '
            'registrada em ml_cookie_atualizado_em). Confirme e renove '
            'ML_COOKIE/ML_CSRF_TOKEN se necessário.'
        )
    else:
        mensagem = (
            f'Cookie do Mercado Livre deve vencer em {dias_restantes} dia(s), com base '
            'na estimativa configurada (ml_cookie_validade_dias_esperada). Renove '
            'ML_COOKIE/ML_CSRF_TOKEN no .env preventivamente.'
        )
    enviar_alerta_operador(mensagem, categoria='ml_cookie_prestes_a_vencer')
    return True
