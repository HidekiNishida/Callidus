---
id: debugging_root_cause
name: Depuração Sistemática e Análise de Causa Raiz
description: Diagnóstico metodológico de falhas, formulação de hipóteses, isolamento da causa fundamental e correção cirúrgica sem mascarar sintomas.
version: 1.0.0
required_tools:
  - file_read
  - grep_search
  - pytest_run
  - shell_exec
  - file_edit
applies_to_kinds:
  - MODEL_OPERATION
  - VERIFICATION
  - SUBSYSTEM
keywords:
  - bug
  - erro
  - falha
  - corrigir
  - diagnosticar
  - investigar
  - quebrou
  - crash
  - exception
  - traceback
  - fix
  - reparar
  - consertar
  - regressão
---

## Critérios de ativação
- Correção de bugs, exceções em runtime, quebras de testes ou regressões
- Investigação de comportamentos anômalos relatados

## Quando não utilizar
- Nunca altere testes para mascarar bugs de implementação
- Não tente correções por tentativa e erro sem identificar a causa

## Procedimentos operacionais
1. Reproduza a falha com comando ou teste objetivo e capture os logs/traces
2. Formule hipóteses refutáveis sobre a origem da discrepância
3. Isole o ponto exato da divergência no fluxo de dados ou lógica
4. Aplique a correção na causa fundamental (não em sintomas periféricos)
5. Execute os testes para comprovar a resolução e ausência de regressões

## Critérios de validação
- O teste ou cenário reproduzível passa comprovadamente
- Nenhum teste prévio foi quebrado

## ⚠️ Riscos
- Mascarar o defeito com tratamento genérico (ex.: catch-all silencioso)
- Introduzir regressões em fluxos que dependiam do comportamento anterior