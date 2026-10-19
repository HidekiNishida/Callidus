---
id: system_architecture
name: Arquitetura de Sistemas e Decomposição
description: Definição de fronteiras entre módulos, fluxo de dados, separação de responsabilidades e contratos de interface consistentes.
version: 1.0.0
required_tools:
  - file_read
  - file_list
  - grep_search
applies_to_kinds:
  - OBJECTIVE
  - SUBSYSTEM
  - PLANNING
keywords:
  - arquitetura
  - decompor
  - módulos
  - estrutura
  - design
  - fronteiras
  - contratos
  - subsistemas
  - planejamento
  - camadas
  - dependências
---

## Critérios de ativação
- Tarefas de planejamento de novas camadas, refatorações globais ou decomposição complexa

## Quando não utilizar
- Tarefas simples e pontuais onde abstrações adicionais adicionariam overhead sem valor

## Procedimentos operacionais
1. Mapeie o fluxo de dados real e as dependências atuais entre módulos
2. Isole responsabilidades garantindo baixo acoplamento e alta coesão
3. Especifique contratos explícitos (schemas, enums, protocolos) para fronteiras
4. Subdivida subsistemas em nós executáveis e auditáveis

## Critérios de validação
- Diagramas e contratos de interface consistentes
- Ausência de dependências circulares

## Riscos
- Sobre-engenharia com abstrações vazias ou excesso de indireção
