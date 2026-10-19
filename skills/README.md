# Catálogo de Skills do Agente de IA Local

Este diretório contém as **Skills** (competências reutilizáveis) do Agente. Cada arquivo define metadados, critérios de ativação, proibições, procedimentos práticos, ferramentas autorizadas, regras de validação, riscos e palavras-chave.

O catálogo é a **fonte de verdade** das competências: o runtime o lê em [`src/agent/skills/catalog/loader.py`](/src/agent/skills/catalog/loader.py) e o converte em `SkillSpec`. Uma skill do **projeto** (`<project_root>/skills/*.md`) sobrescreve a do repositório pelo mesmo `id`.

## Formato de uma Skill

Cada Skill segue a convenção de frontmatter YAML e seções Markdown:

```markdown
---
id: nome_da_skill
name: Nome Amigável
description: Breve resumo da competência e finalidade.
version: 1.0.0
required_tools:
  - file_read
  - pytest_run
applies_to_kinds:
  - MODEL_OPERATION
keywords:
  - palavra
  - outra
---

## Critérios de ativação
- Quando utilizar esta competência

## Quando não utilizar
- Situações proibidas ou inadequadas

## Procedimentos operacionais
1. Passo inicial
2. Próximos passos

## Critérios de validação
- Como verificar que a execução foi bem-sucedida

## Riscos
- O que a execução precisa respeitar
```

| Seção / campo | Vira | Efeito |
|---------------|------|--------|
| `activation_criteria` | `SkillSpec.activation_criteria` | sinaliza quando a skill se aplica (+1 no score) |
| `prohibited_criteria` | `SkillSpec.prohibited_criteria` | impede o uso indevido (ex.: leitura pura) |
| `required_tools` | `SkillSpec.required_tools` | compatibilidade com as ferramentas disponíveis (+0,5) |
| `procedures` | `SkillSpec.procedures` | entram no prompt como passos operacionais |
| `validation_rules` | `SkillSpec.validation_rules` | entram no prompt como critério de validação |
| `risk_factors` | `SkillSpec.risk_factors` | entram no prompt como controle de riscos |
| `keywords` | `SkillSpec.keywords` | ativação por palavra-chave no objetivo (+2 por termo) |
| `applies_to_kinds` | `SkillSpec.applies_to_kinds` | ativação por tipo de tarefa (+1,5) |

## Skills catalogadas

| Arquivo | Identificador | Finalidade |
|---------|---------------|------------|
| [`software-engineering.md`](./software-engineering.md) | `software_engineering` | Construção modular, tipagem estática e compatibilidade |
| [`debugging-root-cause.md`](./debugging-root-cause.md) | `debugging_root_cause` | Diagnóstico metódico, hipóteses e correção cirúrgica |
| [`testing-quality-assurance.md`](./testing-quality-assurance.md) | `testing_quality_assurance` | Testes determinísticos e garantia de requisitos |
| [`refactoring-clean-code.md`](./refactoring-clean-code.md) | `refactoring_clean_code` | Melhoria estrutural sem alteração comportamental |
| [`system-architecture.md`](./system-architecture.md) | `system_architecture` | Fronteiras entre subsistemas e contratos formais |
| [`technical-writing.md`](./technical-writing.md) | `technical_writing` | Documentação técnica hierárquica e sincronizada |

## Como uma skill é ativada

1. A estratégia profissional do pedido define a **especialidade líder** e as **revisoras**.
2. `SkillSelector` pontua o catálogo por palavra-chave, tipo de tarefa e ferramentas disponíveis.
3. Os critérios de não-ativação são aplicados antes (leitura pura não recebe skill de escrita).
4. As skills vencedoras são renderizadas como bloco de prompt, limitado a uma fração do orçamento do modelo.

Detalhes da arquitetura: [skills-estrategia.md](/docs/architecture/skills-estrategia.md) · Runtime: [src/agent/skills/README.md](/src/agent/skills/README.md)
