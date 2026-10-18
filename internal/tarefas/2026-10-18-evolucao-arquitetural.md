# Checklist: Evolução arquitetural — decomposição adaptativa, contexto suficiente, conclusão verificável

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-10-18 |
| Atualizado em | 2026-10-18 |
| Agente / tarefa | Evolução arquitetural (fases A–G) |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md) |

## Objetivo

O orquestrador decompõe só o necessário, monta contexto suficiente por operação, classifica falhas, replaneja por política e só declara conclusão com evidência verificável. Mudança incremental, preservando dados SQLite e a API.

## Próxima ação

Decidir com o dono como tratar o WIP não commitado em `runner.py`, `consolidation.py`, `replan.py` e afins; depois, unidade 2.

## Diagnóstico (fase A — evidências)

| # | Achado | Onde |
|---|--------|------|
| A1 | `python` inexistente no macOS: toda verificação pytest/script falhava com `FileNotFoundError` não tratado | `tools/builtins.py` (**corrigido na unidade 1**) |
| A2 | Corte fixo de profundidade 6 vira folha forçada | `orchestrator/runner.py` `_depth ≥ 6` |
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

## Etapas

- [x] Criar este arquivo a partir do modelo e preencher metadados
- [x] Identificar ramos de regras necessários no hub
- [x] Fase A: inspeção do código real e baseline de testes (HEAD: 5 falhas; WIP: +2)
- [x] Unidade 1: interpretador Python / erro de configuração (`tools/builtins.py`, testes, `ferramentas.md`, `resume.md`)
- [ ] Decisão sobre o WIP não commitado
- [ ] Unidades 2–11
- [ ] Escolher dimensões de teste aplicáveis ([validacoes-testes.md](/docs/regras/validacoes-testes.md))
- [ ] Verificação final: código ↔ docs ↔ checklists ↔ regras ([verificacao-final.md](/docs/regras/verificacao-final.md))
- [ ] Marcar estado como `concluída` e listar artefatos

## Bloqueios

- WIP não commitado do dono está nos arquivos das unidades 3–9; commitar essas unidades sem decidir o destino do WIP misturaria mudanças alheias.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/tools/builtins.py` | `python_for`, erro `configuration` |
| `/tests/test_dev_tools.py` | testes da unidade 1 |
| `/docs/architecture/ferramentas.md` | interpretador e categoria |

## Notas de retomada

Baseline após unidade 1: 99 passam, 2 falham (`test_parent_not_completed_without_verification_evidence`, `test_run_writes_final_answer`), ambas causadas pelo WIP de `consolidation.py`/`runner.py`. Cenários numerados = seção 12 do pedido.
