# Execução de Tarefa (`orchestrator/execution/`) — Como uma Etapa Roda

![fluxos](/media/icons/fluxos.svg){width=48}

O pacote onde **uma** tarefa da árvore é executada: o despacho (MCP, modelo, ferramenta do plano,
verificação), a operação de modelo, a escrita do arquivo e a evidência.

O [`runner.py`](../runner.py) continua sendo o dono do **ciclo** (quando rodar, qual etapa,
quando pausar); este pacote é o dono do **como**.

## 📁 Arquivos

| Arquivo | Símbolos principais | Responsabilidade |
|---------|---------------------|------------------|
| [`executor.py`](executor.py) | `TaskExecutor` | Despacho da etapa: MCP → resposta final → operação de modelo → ferramenta do plano → verificação → consolidação dos filhos |
| [`model_operation.py`](model_operation.py) | `ModelOperation` | Fluxo da operação de modelo: contexto, ciclo de ferramentas, protocolo JSON da alteração e recusa de escrita |
| [`verification` (em `executor.py`)](executor.py) | `TaskExecutor.finalize_verification` | Verificação proporcional ao risco + registro da evidência + plano de recuperação |
| [`runtime.py`](runtime.py) | `ExecutionRuntime` | Colaboradores da execução (sessão, configuração, tarefas, tentativas, ferramentas, fábrica de provedor) |
| [`providers.py`](providers.py) | `select_provider`, `profile_from_config`, `supports_tool_loop`, `apply_provider_usage` | Escolha do provedor, perfil do modelo e contabilidade de tokens |
| [`guards.py`](guards.py) | `write_refusal_reason`, `operation_tools_for`, `payload_is_usable`, `evidence_state` | Permissões de escrita (vêm do pedido, nunca do modelo) e leitura do payload do modelo |
| [`tool_results.py`](tool_results.py) | `is_informative_test_result`, `test_summary` | Distingue "a ferramenta quebrou" de "a suíte rodou e reprovou" |
| [`writes.py`](writes.py) | `write_tool_from_payload`, `implicit_spec`, `model_refusal_result`, `tool_refusal_result` | Traduz a resposta do modelo em escrita, em critério de verificação e em resultado de recusa |
| [`journal.py`](journal.py) | `note_thought`, `remember_failure` | Diário da execução: o que está acontecendo e o que já falhou |
| [`workspace.py`](workspace.py) | `work_root` | Resolve a pasta de trabalho (projeto ou conversa) |

## 🧠 Contratos

| Entrada | Quem chama | Garantia |
|---------|-----------|----------|
| `TaskExecutor.execute(run, project, task, config, work_root)` | `RunOrchestrator._step_body` | Devolve `{"action", "task_id", ...}`; a etapa fica em um estado coerente |
| `TaskExecutor.finalize_verification(...)` | `execute`, `write_final_answer` | Grava `EvidenceModel`; nunca aprova o resultado de quem executou |
| `ExecutionRuntime.provider_factory` | `RunOrchestrator` | Ponto de injeção do provedor (mesmo lugar onde os testes injetam o seu) |

## 🧠 Invariantes

- **A verificação é independente de quem executa**: o modelo propõe, o verificador julga.
- **A recusa de escrita é resultado, não bloqueio**: repetir o mesmo pedido não muda a permissão.
- **A evidência nunca é apagada**: reprovar reabre a etapa, mas o histórico permanece.
- **O provedor é explícito**: nome desconhecido é erro; o mock só entra com autorização.

## 🧪 Testes

```bash
pytest tests/test_model_tool_operation.py -v        # operação de modelo e ciclo de ferramentas
pytest tests/test_independent_verification.py -v    # verificação independente
pytest tests/test_proportional_verification.py -v   # verificação proporcional ao risco
pytest tests/test_request_permissions.py -v         # recusa de escrita (somente leitura, régua protegida)
```

---

**Voltar:** [orchestrator/README.md](../README.md) · **src/agent:** [src/agent/README.md](../../README.md) · **Raiz:** [README.md](../../../../README.md)