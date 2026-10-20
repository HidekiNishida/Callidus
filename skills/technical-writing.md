---
id: technical_writing
name: Documentação Técnica e Comunicação Estruturada
description: Elaboração de documentação hierárquica clara, diagramas, resumos de arquitetura e sincronização rigorosa com o código real.
version: 1.0.0
required_tools:
  - file_read
  - file_write
  - file_edit
  - shell_exec
applies_to_kinds:
  - MODEL_OPERATION
  - CLOSING
  - OBJECTIVE
keywords:
  - documentar
  - documentação
  - docs
  - readme
  - resume
  - guia
  - manual
  - explicar
  - diagrama
  - especificação
---

![desenvolvimento](/media/icons/desenvolvimento.svg){width=48}

## Critérios de ativação
- Criação ou atualização de documentação, guias, READMEs ou resumos técnicos

## Quando não utilizar
- Não documente funcionalidades ainda não implementadas como se estivessem prontas

## Procedimentos operacionais
1. Estabeleça propósito, contexto de execução, entradas e saídas claras
2. Utilize links markdown navegáveis para arquivos e símbolos de código
3. Mantenha diagramas e tabelas alinhados à implementação
4. Atualize arquivos de inventário e execute verificações automáticas de integridade

## Critérios de validação
- Links e referências válidos
- Documentação passa em checagens automáticas de integridade

## ⚠️ Riscos
- Documentação obsoleta ou divergente da implementação real