# Checklist: transformação organizacional do Callidus

Checkpoint versionado da missão que dá ao Callidus uma organização de engenharia: papéis, propriedade, contrato de trabalho, handoff, portões e métricas.

| Campo | Valor |
|-------|-------|
| Estado | concluída (com pendências registradas) |
| Criado em | 2026-11-03 |
| Atualizado em | 2026-11-04 |
| Agente / tarefa | Claude Code — missão "plataforma de engenharia autônoma" |
| Regras consultadas | [AGENTS.md](/AGENTS.md), [Hub](/docs/regras/README.md), [arquitetura](/docs/architecture/README.md) |

## 🎯 Objetivo

Toda tarefa do Callidus passa a ter equipe, papel, revisor, escopo e etapa de trabalho rastreáveis; o conhecimento passa entre agentes por handoff estruturado; a qualidade é vista em portões calculados a partir das evidências; os indicadores de entrega têm numerador e denominador. Sem segunda máquina de estados, sem segundo verificador, sem coluna nova no banco.

## Próxima ação

Comparação específica concluída em 2026-11-04: 3 rodadas × 6 cenários antes/depois, com resultado misto e inconclusivo. Próxima ação: ampliar o G1 do projeto (≥15 cenários e sessão longa) e revisar `aceite_total`; recomendações restantes em [final-audit.md](/docs/engineering/final-audit.md#-recomendações).

## 🔄 Estado por fase

- [x] Fase 0 — auditoria e baseline ([audit.md](/docs/engineering/audit.md))
- [x] Fase 1–2 — governança e CI: Ruff em `[dev]`, sintaxe JavaScript no `scripts/ci.py`, `.github/workflows/ci.yml`, documentos desatualizados corrigidos
- [x] Fase 3 — modelo organizacional: catálogo de equipes, papéis, especialidades e propriedade no domínio (`domain/organization.py`)
- [x] Fase 4–5 — contrato de trabalho, atribuição determinística (`ensure_agent`), contexto com responsabilidade e handoff estruturado (`record_task_result`)
- [x] Fase 6–7 — portões G0–G4 e avaliação em cinco dimensões (`domain/work_flow.py`), indicadores de entrega (`delivery_metrics`)
- [x] Fase 8 — API (`/organization`, `/tasks/{id}/work-item`, `/tasks/{id}/gates`, `/tasks/{id}/handoff`, `POST /tasks/{id}/reviews`, `/projects/{id}/board`) e aba Organização
- [x] Fase 10 — cenários de aceitação A–J em testes determinísticos (`tests/test_organization_api.py`)
- [x] Fase 11 — reconciliação documental e auditoria final ([final-audit.md](/docs/engineering/final-audit.md))
- [x] Comparação real antes/depois desta missão: `a43d9c3` vs `550d733`, mesmo script, `gpt-oss:20b`, 3 × 6 cenários; resultado inconclusivo, sem evidência de ganho agregado de confiabilidade ([benchmarking.md](/docs/engineering/benchmarking.md#-organização-de-engenharia--antes-e-depois-2026-11-04)). O G1 amplo do projeto continua pendente.

## 🧾 Decisões

| Decisão | Motivo |
|---------|--------|
| Organização em `metadata_json` de tarefa e agente, sem coluna nova | o esquema já tem o campo; evita migração e preserva o contrato de persistência (AGENTS.md §9) |
| Etapa Kanban **derivada** de `TaskStatus` + evidências | a mission pede não criar segunda máquina de estados |
| Portões leem evidências do `VerificationGate` | existe um portão único; um segundo verificador seria duplicação |
| Atribuição determinística, sem inferência | barato, explicável, funciona com modelo pequeno |
| CI remoto ligado | pedido explícito do dono nesta missão (antes adiado em 2026-10-21; AGENTS.md §17) |
| Trabalho de outra sessão na árvore não é tocado nem comitado | AGENTS.md §18 |
| Rotas de leitura calculam o contrato sem gravar | abrir o quadro num banco real não pode reescrever o `metadata_json` de todas as tarefas |
| Revisão que reprova tarefa `COMPLETED` não reabre o status | reabrir faria o laço autônomo reexecutar; a etapa fica em `REWORK` e conta como defeito escapado |
| `preencher_resume.py` só com os caminhos desta missão | o script não respeita o `.gitignore` (criou seções de `node_modules/`, `.playwright-mcp/`, `lab/out/`); o excesso foi removido |

## 🧪 Testes executados

| Quando | Comando | Resultado |
|--------|---------|-----------|
| baseline | `python scripts/ci.py --rapido` | todos os passos verdes exceto `resume.md`, reprovado por símbolos da sessão paralela ainda sem commit |
| baseline | `pytest -q` numa cópia limpa do `HEAD` | 1433 passaram |
| entrega | mesma cópia + arquivos desta missão | 1461 passaram, 0 falhas |
| entrega | `node tests/web/e2e.mjs` | todos os cenários passaram |
| entrega | `node --test tests/web/*.test.mjs` | 127 passaram |
| entrega | conferência visual com banco descartável (`CALLIDUS_DATABASE_URL` no scratchpad) | quadro, portões e revisão funcionando |
| 2026-11-04 | `lab/avaliar.py` em worktrees isolados, antes/depois, 3 rodadas × 6 cenários, `gpt-oss:20b` | 14/18 vs 13/18 runs concluídos; 18/21 vs 16/21 requisitos provados; medianas de tempo 924,3 s vs 795,3 s; resultado inconclusivo. Seis JSONs preservados localmente em `lab/out/g1-org-2026-11-04/`. |

## Bloqueios

- `resume.md` reprova enquanto a outra sessão não descrever os próprios símbolos (`lab/bateria.py`, `browser.py`, `builtins.py`…) e não carimbar. Não é desta missão.
- Na árvore de trabalho, `tests/test_multirequisito_regressions.py::test_edit_file_with_empty_old_string_appends` falha só com as mudanças não comitadas da outra sessão em `tools/builtins.py`.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/docs/engineering/audit.md` | diagnóstico da Fase 0 |
| `/.github/workflows/ci.yml` | CI remoto |
| `/docs/engineering/final-audit.md` | auditoria final |
| `/src/agent/domain/organization.py`, `/src/agent/domain/work_flow.py` | domínio |
| `/src/agent/services/organization_service.py`, `/src/agent/api/organization_routes.py` | aplicação e API |

## Notas de retomada

Confira `git log --oneline` contra as fases marcadas acima; cada fase entra num commit próprio. Antes de comitar, `git add` só dos caminhos desta missão.
