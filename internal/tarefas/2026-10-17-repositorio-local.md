# Checklist: Repositório local com documentação do Project

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-17 |
| Atualizado em | 2026-10-17 |
| Agente / tarefa | bc-7874d165 — migrar store → git local |
| Regras consultadas | [Hub](/docs/regras/README.md) |

## Objetivo

Criar em `~/Documents/Projetos/Agente de IA Local/` um repositório git espelhando docs/media/internal do Agent Store, reescrever links `/cursor/stores/self/…` e registrar README + estratégia git vs Context.

## Próxima ação

Nenhuma — tarefa encerrada; opcional: configurar remote GitHub e script de sync store ↔ repo.

## Etapas

- [x] Criar este arquivo a partir do modelo e preencher metadados
- [x] Identificar ramos de regras necessários no hub
- [x] Verificar source no Agent Store (`bc-b167c6af-…/files/`)
- [x] Copiar `docs/`, `media/`, `internal/`, `preferences.md`, `notes.md`
- [x] Reescrever links para convenção `/docs/…`, `/media/…`, `/internal/…`
- [x] Atualizar `docs/project-context.md` (repo canônico + sync)
- [x] Adicionar `README.md` e `.gitignore`
- [x] Validar links internos em Markdown
- [x] `git init` + commit inicial em português
- [x] Verificação final: docs ↔ checklists ↔ regras ([verificacao-final.md](/docs/regras/verificacao-final.md))
- [x] Marcar estado como `concluída` e listar artefatos

## Bloqueios

- Nenhum.

## Artefatos

| Path | Notas |
|------|-------|
| `/README.md` | Entrada humana + agentes |
| `/docs/project-context.md` | Identidade, sync git/Context |
| `/internal/tarefas/2026-10-17-repositorio-local.md` | Este checklist |
| `~/Documents/Projetos/Agente de IA Local/` | Raiz do repositório git |

## Notas de retomada

Commit inicial contém cópia completa do store em 2026-10-17. Follow-ups sugeridos: remote GitHub, script rsync store↔repo, abrir este folder como workspace Cursor.
