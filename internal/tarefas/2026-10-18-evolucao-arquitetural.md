# Checklist: Evolução arquitetural — decomposição adaptativa, contexto suficiente, conclusão verificável

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-18 |
| Atualizado em | 2026-10-18 |
| Agente / tarefa | Evolução arquitetural (fases A–G) |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md) |

## 🎯 Objetivo

O orquestrador decompõe só o necessário, monta contexto suficiente por operação, classifica falhas, replaneja por política e só declara conclusão com evidência verificável. Mudança incremental, preservando dados SQLite e a API.

## Próxima ação

Nenhuma: evolução concluída. Sequência: [validação do plano, verificação independente e progresso real](/internal/tarefas/2026-10-18-validacao-verificacao-progresso.md).

## ⚠️ Diagnóstico (fase A — evidências)

| # | Achado | Onde |
|---|--------|------|
| A1 | `python` inexistente no macOS: toda verificação pytest/script falhava com `FileNotFoundError` não tratado | `tools/builtins.py` (**corrigido na unidade 1**) |
| A2 | Corte fixo de profundidade 6 vira folha forçada | `orchestrator/runner.py` `_depth ≥ 6` (**corrigido na unidade 7**) |
| A3 | Contexto obrigatório acima do orçamento lança `ValueError` fora de try; tarefa fica RUNNING | `context/assembler.py`, `runner._execute_task` |
| A4 | JSON inválido do modelo grava tentativa `success=True` e repete o prompt idêntico até 8 tentativas | `runner._execute_task` (model_operation) |
| A5 | Contexto da operação não leva motivo das falhas anteriores nem resultados de dependências | `context/operation_builder.py` |
| A6 | Atomizador inalcançável para `model_operation` (`executable_leaf` vem antes) | `runner`, `atomizer.py` |
| A7 | `MAX_REPLANS=2` fixo; depois disso o pai com filho falho nunca é escolhido e o run fica "aguardando" | `replan.py`, `_pick_next_task` |
| A8 | `global_verify_failed` nunca encerra o run (laço) | `runner._step_body` |
| A9 | Sem taxonomia de falhas (recuperável, trocar estratégia, dependência, externo, configuração, limite) | todo o orquestrador |
| A10 | WIP de `consolidation.py` conclui pai com `achieved=False` — contraria "pai nunca conta como sucesso com requisito falho" | `consolidation.py` (WIP) |
| A11 | `_pick_next_task` varre todas as tarefas do banco; ordem entre irmãos implícita | `runner._pick_next_task` |
| A12 | `EvidenceModel.attempt_id` nunca preenchido | `runner._finalize_verification` |

## Plano (unidades pequenas, cada uma com teste)

| Unidade | Fase | Mudança | Depende de | Risco | Aceite |
|---------|------|---------|-----------|-------|--------|
| 1 | B | Interpretador Python correto + erro de executável categorizado | — | baixo | 5 falhas antigas passam; teste de categoria |
| 2 | B | Taxonomia `FailureCategory` + classificador puro (erro de tool/modelo/contexto → categoria) | 1 | baixo | testes unitários por categoria |
| 3 | C | Erro de orçamento/contexto vira falha `context_overflow` registrada (snapshot, sem RUNNING preso) com recuperação: reduzir opcionais → atomizar | 2 | médio (WIP) | cenários 7 e 8 |
| 4 | C | JSON inválido = tentativa falha; reenvio com motivo da falha e estratégia diferente; nunca prompt idêntico | 2 | médio (WIP) | cenários 10 e 13 |
| 5 | C | Contexto suficiente: objetivo global, contrato, resultados de dependências, falhas anteriores | 4 | médio | cenário 9 |
| 6 | D | Política de replanejamento por categoria (substitui `MAX_REPLANS`); limite salva estado recuperável e explica | 2 | alto (WIP) | cenários 6, 19 |
| 7 | D | Profundidade funcional (orçamento por ramo + detecção de repetição) no lugar do corte 6 | 6 | médio | cenários 2, 3, 14 |
| 8 | E | Consolidação: pai com requisito falho nunca COMPLETED; aceitação global com pendências encerra run como falho recuperável | 6 | alto (WIP) | cenários 17, 18 |
| 9 | E | Verificação proporcional ao risco; inconclusivo nunca passa; evidência ligada à tentativa | 8 | médio | cenários 11, 12 |
| 10 | F | Retomada: reabrir banco, revalidar arquivos (hash) antes de repetir operação | 5 | médio | cenários 15, 16 |
| 11 | G | Métricas de progresso verificável; ponta a ponta multi-etapa | todas | baixo | cenários 1, 4, 5, 20 |

## 🔄 Etapas

- [x] Criar este arquivo a partir do modelo e preencher metadados
- [x] Identificar ramos de regras necessários no hub
- [x] Fase A: inspeção do código real e baseline de testes (HEAD: 5 falhas; WIP: +2)
- [x] Unidade 1: interpretador Python / erro de configuração (`tools/builtins.py`, testes, `ferramentas.md`, `resume.md`)
- [x] Decisão sobre o WIP: commitado à parte (`1b92a41`); consolidação segue a especificação
- [x] Unidade 2: taxonomia `domain/failures.py`, falhas gravadas em tentativa/evento/`last_failure`, evidência com `attempt_id`, JSON inválido = tentativa falha
- [x] Unidade 3: `ContextBudgetError`, snapshot do estouro, compactação sem perda, `blocked_context` explicado, `RUNNING → BLOCKED`
- [x] Unidade 4: `tentativas-anteriores` no contexto, `retry_hint`, impressão do prompt (`repeated_prompt`), `num_predict` dobrado em resposta cortada, saída da verificação no detalhe
- [x] Unidade 8 (antecipada): consolidação segue a especificação, término explicado (`run_stalled`), sem espera infinita; 2 falhas do WIP resolvidas
- [x] Unidade 6: `replan_decision` por categoria, orçamento por linhagem, condição de progresso, filho substituído (`superseded`/`settled`), passo de replanejamento que decompõe de novo
- [x] Unidade 5: arquivos-alvo com conteúdo exato, contrato, objetivo global e resultados das dependências no contexto
- [x] Unidade 9: verificação implícita para escrita, etapa sem ação executa, inconclusivo nunca aprova, evidência com `attempt_id`
- [x] Unidade 7: `_recursion_guard` (objetivo/título repetido acima, `max_tree_depth`, `max_tasks_per_run`) separado da decisão de dividir; corte fixo removido
- [x] Unidade 10: impressão digital na evidência (`verification/fingerprint.py`), só a evidência mais recente e atual vale, `stale_evidence` reabre em VERIFYING (reverifica antes de refazer), retomada após reabrir o banco
- [x] Unidade 11: `orchestrator/progress.py` (progresso = trabalho verificado), `payload.progress` em cada ação, `GET /runs/{id}/metrics`, cenários 1, 4, 5, 20
- [x] Escolher dimensões de teste aplicáveis ([validacoes-testes.md](/docs/regras/validacoes-testes.md))
- [x] Verificação final: código ↔ docs ↔ checklists ↔ regras ([verificacao-final.md](/docs/regras/verificacao-final.md))
- [x] Marcar estado como `concluída` e listar artefatos

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/tools/builtins.py` | `python_for`, erro `configuration` |
| `/tests/test_dev_tools.py` | testes da unidade 1 |
| `/docs/architecture/ferramentas.md` | interpretador e categoria |
| `/src/agent/domain/failures.py` | taxonomia de falhas |
| `/tests/test_failures.py` | testes da unidade 2 |
| `/tests/test_context_recovery.py` | testes da unidade 3 (cenários 7 e 8) |
| `/tests/test_retry_strategy.py` | testes da unidade 4 (cenários 10 e 13) |
| `/tests/test_proportional_verification.py` | testes da unidade 9 (cenários 11, 12) |
| `/tests/test_sufficient_context.py` | testes da unidade 5 (cenário 9) |
| `/tests/test_functional_depth.py` | testes da unidade 7 (cenários 2, 3, 14) |
| `/tests/test_resume_integrity.py` | testes da unidade 10 (cenários 15, 16) |
| `/tests/test_progress_metrics.py` | testes da unidade 11 (cenários 1, 4, 5, 20) |
| `/src/agent/orchestrator/progress.py` | progresso verificável |
| `/src/agent/verification/fingerprint.py` | impressão digital da evidência |
| `/tests/test_run_termination.py` | testes da unidade 8 (cenários 6, 17, 18) |
| `/docs/architecture/context-builder.md` | estouro e compactação |
| `/docs/architecture/execucao-autonoma.md` | seção Falhas categorizadas |

## Notas de retomada

Final: 147 passam, 0 falham. Os 20 cenários do pedido têm teste: 1/4/5/20 `test_progress_metrics`, 2/3/14 `test_functional_depth` (3 também por replanejamento que redecompõe em `test_run_termination`), 6/17/18 `test_run_termination`, 7/8 `test_context_recovery`, 9 `test_sufficient_context`, 10/13 `test_retry_strategy` e `test_decompose_loop`, 11/12 `test_proportional_verification` e `test_retry_strategy`, 15/16 `test_resume_integrity`, 19 `test_run_termination` (configuração) e `test_failures`. Cenários numerados = seção 12 do pedido.