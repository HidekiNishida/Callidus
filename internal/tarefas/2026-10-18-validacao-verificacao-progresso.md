# Checklist: Validação do plano, verificação independente e progresso real

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-10-18 |
| Atualizado em | 2026-10-18 |
| Agente / tarefa | Mecanismos A (plano), B (verificação), C (progresso) — fases A–G |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md) |
| Antecessor | [evolução arquitetural](/internal/tarefas/2026-10-18-evolucao-arquitetural.md) (concluída) |

## Objetivo

Validar o plano antes de executá-lo (cobertura de requisitos e integridade estrutural), aceitar resultados só com evidência independente e distinguir atividade de progresso, com limites operacionais que pausam sem perder trabalho. Mudança incremental, sem tabela nova enquanto as existentes servirem.

## Próxima ação

Unidade 3: evidência com estado explícito, critério, comando e código de saída; verificador de sintaxe; verificação bloqueada ≠ reprovada.

## Diagnóstico (fase A — evidências)

| # | Achado | Onde |
|---|--------|------|
| B1 | Não há requisitos: só `TaskModel.acceptance_criteria` (texto) e `TaskContractModel.acceptance_json` (usado só com `requires_contract`) | `persistence/models.py`, `services/contract_service.py` |
| B2 | `apply_decomposition` ignora em silêncio dependência fora do intervalo ou para si mesma; nada registra o que cada subtarefa cobre | `orchestrator/decomposition.py` |
| B3 | Nenhuma validação do plano antes da execução; só `seal_repeated_steps`, `plan_copies_siblings` e bloqueio de ciclo em `add_dependency` | `decomposition.py`, `task_service.py` |
| B4 | Aceite global olha só tarefas com verificação; resposta final do modelo conclui o run sem evidência de requisito | `orchestrator/global_verify.py` |
| B5 | Evidência tem `passed` (True/False/None); faltam estados bloqueado, não executado e desatualizado gravado; ferramenta ausente vira "reprovado" | `runner._finalize_verification`, `EvidenceModel` |
| B6 | Sem verificador de sintaxe: código Python inválido passa no `file_contains` implícito | `verification/runner.py` |
| B7 | Repetição: só prompt idêntico, saída idêntica e orçamento de replanejamento; mesmo erro com texto diferente passa | `attempt_service.py`, `replan.py` |
| B8 | Limites: `max_attempts_per_task`, `max_orchestrator_steps`, `REPLAN_BUDGET` fixo; sem limite de chamadas, tempo, tokens, ferramentas nem sem-progresso | `config.py` |
| B9 | Run pausado não tem retomada pela API | `api/main.py`, `run_service.py` |

## Decisões de persistência (sem tabela nova)

| Dado | Onde | Por quê |
|------|------|---------|
| Requisitos (id estável, descrição, origem, critério, obrigatório, evidência esperada, estado declarado) | `task_contracts.acceptance_json.requirements` da raiz | o contrato já é "critérios de aceite" da tarefa; API de upsert existente |
| Cobertura (inclusive parcial) | `tasks.metadata_json.covers` | por tarefa, herdável na decomposição |
| Resultado e versões da validação | `metadata_json.plan_validation` do pai + evento `plan.validated` com o plano | metadados para o estado atual, eventos como histórico auditável |
| Estado da evidência, critério, comando, código de saída | `evidence.detail_json` | campo já existente; `created_at` e `attempt_id` já existem |
| Diagnóstico de estagnação e próxima ação | metadados da raiz + evento `run.paused` | retomada lê do banco |

## Plano (unidades pequenas, cada uma com teste)

| Unidade | Fase | Mudança | Risco | Cenários |
|---------|------|---------|-------|----------|
| 1 | C | Requisitos rastreáveis: derivar do objetivo (ou ler do contrato), ids estáveis, `covers` herdado/parcial, estado calculado por evidência | médio | base de 1–9, 18 |
| 2 | B | Validação estrutural determinística do plano (6 resultados), correção automática, bloqueio recuperável, revalidação quando o plano muda | alto | 1–9 |
| 3 | D | Evidência com estado explícito, critério, comando, código de saída; sintaxe Python/JSON; verificação bloqueada ≠ reprovada; desatualizada marcada | médio | 10–15, 17, 29 |
| 4 | D/F | Aceite global por requisito; integração reprovada; correção localizada; relatório parcial | alto | 16, 18, 19, 23, 24, 28 |
| 5 | E | Assinatura normalizada de erro, estagnação, resposta em 10 passos, limites configuráveis, pausa com diagnóstico e `POST /runs/{id}/resume` | alto | 20–22, 25 |
| 6 | G | Métricas de requisitos e pausas, retomada, ponta a ponta com correção, documentação | baixo | 26, 27, 30 |

## Riscos

- Exigir evidência por requisito pode reprovar runs que hoje concluem (pergunta simples, leitura). Mitigação: requisito de resposta aceita a evidência estrutural da resposta final; requisito de mudança exige verificador.
- Validação rígida pode bloquear planos do modelo local que não declaram `covers`. Mitigação: sem `covers` declarado, a cobertura é implícita e o resultado fica "válido com ressalvas" ou "inconclusivo", nunca bloqueia sozinho.
- Gravar progresso e validar a cada passo custa consultas; árvore limitada por `max_tasks_per_run`.
- Testes antigos que montam árvores à mão podem cair na validação; rodar a suíte inteira a cada unidade.

## Etapas

- [x] Criar este arquivo e preencher metadados
- [x] Fase A: inspeção e diagnóstico (baseline 147 passam)
- [x] Unidade 1: `orchestrator/requirements.py` (derivação, ids estáveis no contrato da raiz, `covers` herdado/parcial, `requirement_status`), requisitos no prompt de decomposição
- [x] Unidade 2: `orchestrator/plan_validation.py` (6 vereditos, correção segura, bloqueio `invalid_plan`, versões em `plan.validated`, revalidação por impressão do plano), cobertura carregada no replanejamento
- [ ] Unidade 3
- [ ] Unidade 4
- [ ] Unidade 5
- [ ] Unidade 6
- [ ] Verificação final: código ↔ docs ↔ checklists ↔ regras
- [ ] Marcar estado como `concluída`

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/orchestrator/requirements.py` | requisitos rastreáveis |
| `/tests/test_requirements.py` | testes da unidade 1 |
| `/src/agent/orchestrator/plan_validation.py` | validação do plano |
| `/tests/test_plan_validation.py` | testes da unidade 2 (cenários 1–9) |
| `/docs/architecture/requisitos-verificacao-progresso.md` | documento dos três mecanismos |

## Notas de retomada

Após unidade 2: 165 passam, 0 falham. Cenários numerados = seção 7 do pedido.
