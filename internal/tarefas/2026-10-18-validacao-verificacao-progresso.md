# Checklist: Validação do plano, verificação independente e progresso real

![tarefas](/media/icons/tarefas.svg){width=48}

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-18 |
| Atualizado em | 2026-10-18 |
| Agente / tarefa | Mecanismos A (plano), B (verificação), C (progresso) — fases A–G |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md) |
| Antecessor | [evolução arquitetural](/internal/tarefas/2026-10-18-evolucao-arquitetural.md) (concluída) |

## 🎯 Objetivo

Validar o plano antes de executá-lo (cobertura de requisitos e integridade estrutural), aceitar resultados só com evidência independente e distinguir atividade de progresso, com limites operacionais que pausam sem perder trabalho. Mudança incremental, sem tabela nova enquanto as existentes servirem.

## Próxima ação

Nenhuma: evolução concluída. Melhorias possíveis estão em "Limitações e casos inconclusivos" do [documento](/docs/architecture/requisitos-verificacao-progresso.md#limitações-e-casos-inconclusivos).

## ⚠️ Diagnóstico (fase A — evidências)

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

## ⚠️ Riscos

- Exigir evidência por requisito pode reprovar runs que hoje concluem (pergunta simples, leitura). Mitigação: requisito de resposta aceita a evidência estrutural da resposta final; requisito de mudança exige verificador.
- Validação rígida pode bloquear planos do modelo local que não declaram `covers`. Mitigação: sem `covers` declarado, a cobertura é implícita e o resultado fica "válido com ressalvas" ou "inconclusivo", nunca bloqueia sozinho.
- Gravar progresso e validar a cada passo custa consultas; árvore limitada por `max_tasks_per_run`.
- Testes antigos que montam árvores à mão podem cair na validação; rodar a suíte inteira a cada unidade.

## 🔄 Etapas

- [x] Criar este arquivo e preencher metadados
- [x] Fase A: inspeção e diagnóstico (baseline 147 passam)
- [x] Unidade 1: `orchestrator/requirements.py` (derivação, ids estáveis no contrato da raiz, `covers` herdado/parcial, `requirement_status`), requisitos no prompt de decomposição
- [x] Unidade 2: `orchestrator/plan_validation.py` (6 vereditos, correção segura, bloqueio `invalid_plan`, versões em `plan.validated`, revalidação por impressão do plano), cobertura carregada no replanejamento
- [x] Unidade 3: evidência com estado, critério, comando, código de saída e motivo; sintaxe Python/JSON; verificação bloqueada (`VERIFYING → BLOCKED`) separada de reprovada; desatualizada marcada sem apagar; `file_contains` lê o arquivo inteiro (corrige falso reprovado com quebra final)
- [x] Unidade 4: aceite global exige requisito obrigatório comprovado; etapa de verificação global cobre todos os requisitos; `correct_requirement_gaps` (Atender/Comprovar Rn, uma vez por requisito); relatório de requisitos na conclusão e na parada; corrigida a reabertura inválida COMPLETED → PLANNING em `ensure_global_verification_task`
- [x] Unidade 5: `orchestrator/stagnation.py` (assinatura normalizada de erro e de estratégia, diagnóstico, limites do trecho atual), `_check_stagnation` (resposta em 10 passos: bloqueia, registra, diagnostica, replaneja ou pausa), `_pause_run`, limites em `Settings`/`config.limits`, `RunService.resume_run` e `POST /runs/{id}/resume`, replanejamento compara motivo normalizado; passo em run pausado não executa
- [x] Unidade 6: métricas `requirements`, `stagnation`, `pauses`, `resumes`, `artifacts_validated`; ponta a ponta com uma correção e aceite global; corrigido falso reprovado por bytecode antigo (`pytest` sem gravar `.pyc`; escrita de `.py` apaga o cache dele)
- [x] Verificação final: código ↔ docs ↔ checklists ↔ regras (mapa de cenários e critérios abaixo; `resume.py check` limpo; 188 testes passam)
- [x] Marcar estado como `concluída`

## Cenários da seção 7 → testes

| Cenários | Arquivo |
|----------|---------|
| 1–9 (validação do plano) | `tests/test_plan_validation.py` |
| 10–14, 17, 29 (evidência, sintaxe, bloqueada, inconclusiva, desatualizada, ferramenta ≠ implementação) | `tests/test_independent_verification.py` |
| 15, 24 (sucesso alegado sem evidência), 16, 28 (correção e reabertura localizadas), 18 (requisito pendente), 19 (integração reprovada), 23 (evidência válida) | `tests/test_global_acceptance.py`, `tests/test_independent_verification.py` (código inválido apesar de "pronto") |
| 20 (mesmo erro), 21 (replanejamento sem menos pendências), 22 (estratégia diferente), 25 (limite com estado recuperável) | `tests/test_stagnation_limits.py`, `tests/test_retry_strategy.py` |
| 26 (retomada após interrupção), 27 (alteração externa entre execução e retomada) | `tests/test_resume_integrity.py`, `tests/test_stagnation_limits.py` (pausa e retomada) |
| 30 (ponta a ponta com correção e aceite global) | `tests/test_end_to_end_requirements.py` |

## Critérios finais (seção 10) → evidência

| Critério | Evidência |
|----------|-----------|
| Plano incompleto ou inconsistente identificado antes da execução | `validate_and_repair` ao decompor e `_revalidate_plan`; cenários 1–9 |
| Requisitos rastreáveis após decomposições | ids estáveis no contrato, `covers` herdado e carregado no replanejamento; `test_requirements.py`, cenário 7 |
| Cobertura obrigatória ausente impede falso sucesso global | `evaluate_global_acceptance` por requisito; cenários 18, 19 |
| Evidência proporcional | verificação declarada ou implícita (conteúdo e sintaxe), pytest, comando; cenários 10–12 |
| Afirmação do modelo não substitui verificação | cenários 11, 15, 24 |
| Correção localizada | `reopen_verification_gaps`, `correct_requirement_gaps`; cenários 16, 28 |
| Evidência invalidada não é reutilizada | `desatualizado` e `is_current`; cenários 17, 27 |
| Repetição improdutiva detectada e estratégia alterada com justificativa | `_check_stagnation` com diagnóstico e replanejamento; cenários 20–22 |
| Limites impedem loops sem destruir progresso | `limit_reached`, `_pause_run`, `resume_run`; cenário 25 |
| Interrupção e retomada preservam integridade | cenários 26, 27 |
| Testes de sucesso, falha, regressão e recuperação | 30 cenários mapeados acima |
| Documentação corresponde ao comportamento | `docs/architecture/requisitos-verificacao-progresso.md`, `execucao-autonoma.md`, `maquina-estados.md`, `modelo-dados.md`; `resume.md` carimbado |
| Ponta a ponta verificável com várias etapas | cenário 30 |

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/orchestrator/requirements.py` | requisitos rastreáveis |
| `/tests/test_requirements.py` | testes da unidade 1 |
| `/src/agent/orchestrator/plan_validation.py` | validação do plano |
| `/tests/test_plan_validation.py` | testes da unidade 2 (cenários 1–9) |
| `/tests/test_independent_verification.py` | testes da unidade 3 (cenários 10–15, 17, 29) |
| `/tests/test_global_acceptance.py` | testes da unidade 4 (cenários 15, 16, 18, 19, 23, 24, 28) |
| `/src/agent/orchestrator/stagnation.py` | repetição, diagnóstico e limites |
| `/tests/test_stagnation_limits.py` | testes da unidade 5 (cenários 20, 21, 22, 25) |
| `/tests/test_end_to_end_requirements.py` | ponta a ponta (cenário 30) |
| `/docs/architecture/requisitos-verificacao-progresso.md` | documento dos três mecanismos |

## Notas de retomada

Após unidade 6: 188 passam, 0 falham. Cenários numerados = seção 7 do pedido.