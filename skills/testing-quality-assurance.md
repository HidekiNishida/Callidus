---
id: testing_quality_assurance
name: Garantia de Qualidade e Testes Independentes
description: Elaboração e execução de verificações determinísticas, casos de borda, testes de regressão e validação independente de critérios de aceitação.
version: 1.0.0
required_tools:
  - pytest_run
  - shell_exec
  - file_read
  - file_write
applies_to_kinds:
  - VERIFICATION
  - MODEL_OPERATION
  - OBJECTIVE
keywords:
  - teste
  - testes
  - pytest
  - validar
  - verificar
  - qualidade
  - qa
  - cobertura
  - critérios
  - aceite
  - evidência
  - homologação
  - regressão
---

## Critérios de ativação
- Subtarefas de validação e verificação de contratos
- Criação de novos casos de teste para módulos ou APIs

## Quando não utilizar
- Não declare sucesso baseando-se apenas em suposições ou afirmações sem execução real

## Procedimentos operacionais
1. Mapeie critérios de aceitação e contratos da tarefa
2. Crie testes determinísticos cobrindo casos nominais e extremos (nulos, limites, falhas de rede)
3. Execute testes em subprocesso real e capture saídas completas
4. Registre evidências com fingerprint dos arquivos avaliados

## Critérios de validação
- Execução com exit_code == 0
- Todos os critérios de aceite verificados objetivamente

## ⚠️ Riscos
- Testes frágeis que dependem de ordem de execução ou estado global
- Asserções vazias que produzem falso positivo