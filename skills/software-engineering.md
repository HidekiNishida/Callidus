---
id: software_engineering
name: Engenharia de Software e Implementação Modular
description: Construção de código robusto, modular, tipado e sustentável seguindo padrões de projeto e preservando compatibilidade.
version: 1.0.0
required_tools:
  - file_read
  - file_write
  - file_edit
  - shell_exec
applies_to_kinds:
  - MODEL_OPERATION
  - SUBSYSTEM
  - OBJECTIVE
keywords:
  - implementar
  - criar
  - desenvolver
  - funcionalidade
  - feature
  - módulo
  - código
  - backend
  - api
  - classe
  - função
  - service
  - endpoint
  - rota
  - componente
---

## Critérios de ativação
- Criação ou modificação de arquivos de código-fonte, classes, funções e endpoints
- Implementação de funcionalidades novas ou expansão de subsistemas

## Quando não utilizar
- Leituras puras de arquivos ou diagnósticos que não alteram código

## Procedimentos operacionais
1. Inspecione o contexto dos módulos consumidores antes de qualquer alteração
2. Preserve rigorosamente contratos de API existentes e compatibilidade retroativa
3. Adicione anotações de tipo completas e tratamento defensivo de exceções
4. Implemente alterações em passos atômicos e testáveis
5. Minimize dependências externas desnecessárias

## Critérios de validação
- Execução limpa sem erros de sintaxe ou importação
- Testes unitários/integração comprovando a funcionalidade implementada
- Nenhuma quebra em fluxos preexistentes

## ⚠️ Riscos
- Quebra de compatibilidade em APIs públicas ou serviços consumidores
- Efeitos colaterais em estado persistente ou concorrência