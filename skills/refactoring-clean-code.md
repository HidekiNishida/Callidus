---
id: refactoring_clean_code
name: Refatoração e Código Limpo
description: Melhoria da estrutura interna, legibilidade e manutenibilidade do código sem alterar seu comportamento observável externo.
version: 1.0.0
required_tools:
  - file_read
  - file_edit
  - pytest_run
  - grep_search
applies_to_kinds:
  - MODEL_OPERATION
  - SUBSYSTEM
keywords:
  - refatorar
  - refatoração
  - clean code
  - simplificar
  - reestruturar
  - débito técnico
  - limpar código
  - otimizar estrutura
  - desacoplar
---

## Critérios de ativação
- Otimização estrutural, simplificação de complexidade ciclomática e desacoplamento

## Quando não utilizar
- Não realize refatoração sem testes prévios passando
- Não introduza novas funcionalidades durante a refatoração

## Procedimentos operacionais
1. Valide que todos os testes passam na linha de base
2. Identifique pontos de duplicação ou acoplamento excessivo
3. Aplique passos atômicos e seguros (extração, renomeação, encapsulamento)
4. Execute os testes após cada modificação para assegurar paridade comportamental

## Critérios de validação
- 100% dos testes de regressão mantidos passando
- Clareza e manutenibilidade do código melhoradas

## Riscos
- Alteração inadvertida de comportamentos sutis ou casos especiais
