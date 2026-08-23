#!/usr/bin/env bash
# Compara as units versionadas em scripts/ com as instaladas em
# ~/.config/systemd/user/. Existe porque em 2026-08-23 descobrimos que
# `scripts/run-bot.service` apontava para um diretório inexistente e rodaria em
# homologação se alguém o instalasse — a unit em produção tinha 3 anos-luz de
# diferença e ninguém sabia.
#
# Comentários e linhas em branco são ignorados na comparação: a documentação
# vive no lado versionado de propósito (ver o comentário do
# consumir-fila-whatsapp-v2, que registra por que o nome tem sufixo).
#
# Uso: scripts/check-units-drift.sh   (sai 1 se houver divergência)

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.config/systemd/user"

# Unidades que rodam nesta máquina mas NÃO pertencem ao descontos.bot: outros
# projetos e infraestrutura compartilhada. Não são cobradas no inventário.
NAO_NOSSAS=(
    'central-hermes-dashboard-sync.service'
    'central-hermes-dashboard-sync.timer'
    'hermes-gateway.service'
    'pioexplica-telegram-listener.service'
    'launchpadlib-cache-clean.service'
    'launchpadlib-cache-clean.timer'
)

normalizar() { grep -vE '^\s*(#|$)' "$1"; }

e_nossa() {
    local nome="$1"
    for excecao in "${NAO_NOSSAS[@]}"; do
        [[ "$nome" == "$excecao" ]] && return 1
    done
    return 0
}

divergentes=0
faltando=0

for versionada in "${REPO_DIR}"/*.service "${REPO_DIR}"/*.timer; do
    [[ -e "$versionada" ]] || continue
    nome="$(basename "$versionada")"
    instalada="${INSTALL_DIR}/${nome}"
    if [[ ! -f "$instalada" ]]; then
        echo "NÃO INSTALADA   ${nome} (versionada, mas ausente em ${INSTALL_DIR})"
        continue
    fi
    if ! diff -q <(normalizar "$versionada") <(normalizar "$instalada") >/dev/null; then
        echo "DIVERGE         ${nome}"
        diff <(normalizar "$versionada") <(normalizar "$instalada") | sed 's/^/                /'
        divergentes=$((divergentes + 1))
    fi
done

for instalada in "${INSTALL_DIR}"/*.service "${INSTALL_DIR}"/*.timer; do
    [[ -e "$instalada" ]] || continue
    nome="$(basename "$instalada")"
    e_nossa "$nome" || continue
    if [[ ! -f "${REPO_DIR}/${nome}" ]]; then
        echo "NÃO VERSIONADA  ${nome} (roda em produção e não está no Git)"
        faltando=$((faltando + 1))
    fi
done

if (( divergentes == 0 && faltando == 0 )); then
    echo 'OK: units versionadas e instaladas batem (ignorando comentários).'
    exit 0
fi

echo
echo "Resumo: ${divergentes} divergente(s), ${faltando} não versionada(s)."
exit 1
