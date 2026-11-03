# Checklist: transformação organizacional do Callidus

Checkpoint versionado da missão que dá ao Callidus uma organização de engenharia: papéis, propriedade, contrato de trabalho, handoff, portões e métricas.

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-11-03 |
| Atualizado em | 2026-11-03 |
| Agente / tarefa | Claude Code — missão "plataforma de engenharia autônoma" |
| Regras consultadas | [AGENTS.md](/AGENTS.md), [Hub](/docs/regras/README.md), [arquitetura](/docs/architecture/README.md) |

## 🎯 Objetivo

Toda tarefa do Callidus passa a ter equipe, papel, revisor, escopo e etapa de trabalho rastreáveis; o conhecimento passa entre agentes por handoff estruturado; a qualidade é vista em portões calculados a partir das evidências; os indicadores de entrega têm numerador e denominador. Sem segunda máquina de estados, sem segundo verificador, sem coluna nova no banco.

## Próxima ação

Ver a seção **Estado por fase**: a primeira fase não marcada é a próxima.

## 🔄 Estado por fase

- [x] Fase 0 — auditoria e baseline ([audit.md](/docs/engineering/audit.md))
- [x] Fase 1–2 — governança e CI: Ruff em `[dev]`, sintaxe JavaScript no `scripts/ci.py`, `.github/workflows/ci.yml`, documentos desatualizados corrigidos
- [ ] Fase 3 — modelo organizacional: catálogo de equipes, papéis, especialidades e propriedade no domínio
- [ ] Fase 4–5 — contrato de trabalho, atribuição determinística, contexto com responsabilidade e handoff estruturado
- [ ] Fase 6–7 — portões G0–G4 calculados e indicadores de entrega
- [ ] Fase 8 — API (`/organization`, `/tasks/{id}/work-item`, `/tasks/{id}/gates`, `/agents/{id}/handoff`) e aba Organização
- [ ] Fase 10 — cenários de aceitação A–J em testes determinísticos
- [ ] Fase 11 — reconciliação documental e auditoria final ([final-audit.md](/docs/engineering/README.md))

## 🧾 Decisões

| Decisão | Motivo |
|---------|--------|
| Organização em `metadata_json` de tarefa e agente, sem coluna nova | o esquema já tem o campo; evita migração e preserva o contrato de persistência (AGENTS.md §9) |
| Etapa Kanban **derivada** de `TaskStatus` + evidências | a mission pede não criar segunda máquina de estados |
| Portões leem evidências do `VerificationGate` | existe um portão único; um segundo verificador seria duplicação |
| Atribuição determinística, sem inferência | barato, explicável, funciona com modelo pequeno |
| CI remoto ligado | pedido explícito do dono nesta missão (antes adiado em 2026-10-21; AGENTS.md §17) |
| Trabalho de outra sessão na árvore não é tocado nem comitado | AGENTS.md §18 |

## 🧪 Testes executados

| Quando | Comando | Resultado |
|--------|---------|-----------|
| baseline | `python scripts/ci.py --rapido` | todos os passos verdes exceto `resume.md`, reprovado por símbolos da sessão paralela ainda sem commit |

## Bloqueios

- `resume.md` reprova enquanto a outra sessão não descrever os próprios símbolos (`lab/bateria.py`, `browser.py`, `builtins.py`…). Não é desta missão.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/docs/engineering/audit.md` | diagnóstico da Fase 0 |
| `/.github/workflows/ci.yml` | CI remoto |

## Notas de retomada

Confira `git log --oneline` contra as fases marcadas acima; cada fase entra num commit próprio. Antes de comitar, `git add` só dos caminhos desta missão.
