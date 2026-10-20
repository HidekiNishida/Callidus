# `src/agent/skills/` — Skills do Callidus

![conceitos](/media/icons/conceitos.svg){width=48}

Competências reutilizáveis injetadas sob demanda no contexto da operação.

| Módulo | Papel |
|--------|-------|
| [`models.py`](./models.py) | Contrato `SkillSpec` (metadados, critérios, procedimentos, validação, riscos) e `SkillMatch` |
| [`builtins.py`](./builtins.py) | Skills nativas mínimas, garantidas mesmo sem o repositório |
| [`catalog/loader.py`](./catalog/loader.py) | Lê o catálogo `skills/*.md` (fonte de verdade) e converte em `SkillSpec` |
| [`discovery.py`](./discovery.py) | `SkillRegistry`: junta built-ins, catálogo do repositório e skills do projeto |
| [`selector.py`](./selector.py) | `SkillSelector`: escolhe as skills relevantes dentro do orçamento de contexto |

Voltar ao [README do Callidus](/src/agent/README.md) · Catálogo editável: [`/skills/`](/skills/README.md)