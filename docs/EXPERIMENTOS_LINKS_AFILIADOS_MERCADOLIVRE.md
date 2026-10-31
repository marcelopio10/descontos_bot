# Experimentos de geradores de links afiliados do Mercado Livre

Status: isolado, mockado e não adotado em produção.

## Regras

- Nenhum módulo desta pasta é importado por `apps/` ou pelo caminho de produção.
- Não usar credenciais, cookies ou sessões reais em experimentos.
- Sem sandbox/conta de teste aprovada, qualidade do link fica “não medida”.
- Não criar montagem manual de parâmetros afiliados.

## Candidatos públicos

| Solução | Autenticação/sessão | API pública documentada | Custo público observado | Riscos | Resultado |
|---|---|---|---|---|---|
| Bot do Afiliado | contrato não confirmado na página pública; não enviar credenciais | não confirmado | plano base anunciado a partir de R$ 99/mês, módulos sob demanda | contrato, rate limit, termos e qualidade não verificáveis | não adotado |
| AfiliTools | extensão sincroniza sessão autenticada/cookies e serviço chama endpoint do ML | não há contrato público verificável na página consultada | R$ 99/mês e teste de 7 dias anunciados | transferência de sessão, dependência de extensão, termos e segurança | não adotado |
| Motor atual do projeto | `ML_COOKIE`/`ML_CSRF_TOKEN` | endpoint privado existente, não é terceiro | custo não avaliado nesta tarefa | dependência legada; preservado por compatibilidade | fonte oficial do pipeline |

Fontes públicas consultadas em 2026-09-12:

- https://botdoafiliado.com/blog/api-de-afiliados-mercado-livre/
- https://afilitools.com.br/mercadolivre

## Execução

```bash
python3 -m unittest discover -s experiments/mercadolivre_affiliate -p 'test_*.py' -v
```

O teste verifica apenas que os contratos experimentais permanecem isolados e que nenhum request externo é feito. A adoção de qualquer terceiro exigiria aprovação explícita, contrato documentado, avaliação jurídica/termos, sandbox ou conta de teste e um plano separado.
