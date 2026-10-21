# Contexto (`context/`) — Orçamento de Tokens + Montagem de Prompt

Gestão determinística do que cabe na janela de contexto do modelo: componentes com prioridade, compactação seletiva e erro se obrigatórios não couberem.

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`budget.py`](budget.py) | `ContextComponent`, `BudgetResult`, `assemble_messages`, `compact_text`, `ContextBudgetError` | **Motor de orçamento** — prioridades, required vs optional, compactação, erro |
| [`assembler.py`](assembler.py) | `build_operation_context` | **Prompt da operação** — componentes fixos + opcionais (tentativas, contrato, arquivos-alvo, objetivo global, deps) |
| [`operation_builder.py`](operation_builder.py) | `OperationContextBuilder.build_for_task` | **Builder por task** — usa `assembler` + grava `ContextSnapshotModel` |

## 🏗️ Componentes do Prompt (Prioridades)

```python
# assembler.py - build_operation_context
components = [
    ContextComponent(name="regras-globais",    text=global_rules,    required=True,  priority=100),
    ContextComponent(name="objetivo",          text=objective,       required=True,  priority=99),
    ContextComponent(name="critérios",         text=acceptance,      required=True,  priority=98),
    ContextComponent(name="formato-saída",     text=output_format,   required=True,  priority=97),
    ContextComponent(name="regras-projeto",    text=project_rules,   required=False, priority=80),
    ContextComponent(name="skills",            text=skills,          required=False, priority=75),
    ContextComponent(name="contexto-técnico",  text=technical,       required=False, priority=70),
    ContextComponent(name="ferramentas",       text=tools_summary,   required=False, priority=60),
]

optional = [
    ("tentativas-anteriores", previous_failures, True,  96),  # required se existe
    ("contrato",              contract,           True,  95),
    ("arquivos-alvo",         target_files,       True,  94),  # NUNCA compactado (_EXACT)
    ("objetivo-global",       global_objective,   False, 90),
    ("resultados-dependências", dependency_results, False, 85),
]
```

O bloco `tentativas-anteriores` carrega **duas** coisas: o resumo das falhas anteriores
(`describe_failures`) e a **memória de abordagem** (`render_approach`, de
[`agent/orchestrator/approach.py`](../orchestrator/approach.py)) — o que travou, a hipótese, o que
foi tentado, o que será diferente agora e os critérios de sucesso e de fracasso. Sem essa segunda
parte, o modelo recebe a lista do que já falhou e repete a mesma operação.

### Skills no prompt

O bloco `skills` (prioridade 75) traz as competências selecionadas sob demanda
([`src/agent/skills/`](../skills/README.md)):

- a seleção usa a **estratégia profissional** da tarefa quando ela existe (especialidade líder + revisoras);
- o bloco é limitado a **12% do orçamento de entrada** do modelo e a `skills_max_per_operation` skills (2);
- por ser **opcional**, é descartado quando o orçamento aperta — o obrigatório nunca é cortado.

## ⚙️ Orçamento (`budget.py`)

```python
def assemble_messages(profile: ModelProfile, components: list[ContextComponent]) -> BudgetResult:
    # 1. Separa required vs optional
    # 2. Ordena optional por priority (maior primeiro)
    # 3. Adiciona required (sempre cabem → ContextBudgetError se não)
    # 4. Adiciona optional até estourar input_budget
    # 5. Se compact=True: compact_text() em TUDO exceto "arquivos-alvo"
    # 6. Retorna BudgetResult(messages, estimated_tokens, components, strategy_notes)
```

**`compact_text(text)`**: remove linhas duplicadas consecutivas + espaços extras (preserva semântica, não corta conteúdo).

**`ContextBudgetError`**: levantada se required > `input_budget` — orchestrator tenta `compact=True` uma vez, se ainda falha → task `BLOCKED` com detalhe do maior componente.

Esse orçamento é o da **janela de uma chamada**. O teto acumulado da execução, a reserva de conclusão e o registro de cada inferência estão em [orcamento-contexto.md](/docs/architecture/orcamento-contexto.md). `estimated_tokens` do snapshot é a estimativa das mensagens montadas, não o consumo informado pelo provedor.

## ⚙️ OperationContextBuilder (`operation_builder.py`)

```python
class OperationContextBuilder:
    def build_for_task(self, project_id, root_path, task, profile, run_id, compact=False) -> tuple[BudgetResult, ContextSnapshotModel]:
        # 1. Coleta componentes:
        #    - global_rules (guides/capability_line)
        #    - project_rules (AGENTS.md, READMEs via guide_digest)
        #    - objective, acceptance_criteria, scope
        #    - tools_summary (TOOL_CATALOG)
        #    - output_format (JSON schema da operação)
        #    - previous_failures (task.metadata.failures formatado)
        #    - contract (TaskContractModel formatado)
        #    - target_files (conteúdo dos arquivos que a task vai editar)
        #    - global_objective (root.task.objective)
        #    - dependency_results (consolidação dos pais)
        #    - skills (seleção sob demanda, limitada pelo orçamento)
        # 2. Chama build_operation_context(..., compact=compact)
        # 3. Grava ContextSnapshotModel (estimated_tokens, components_json, strategy_notes_json, refs_json)
        # 4. Retorna (BudgetResult, snapshot)
```

## 🔄 Uso no Orquestrador (`runner.py`)

```python
builder = OperationContextBuilder(session)
try:
    budget, snap = builder.build_for_task(project_id=project.id, root_path=root_path, task=task, profile=profile, run_id=run.id)
except ContextBudgetError:
    # Tenta compactado
    budget, snap = builder.build_for_task(..., compact=True)
    # Se ainda falha → _context_overflow → task BLOCKED
```

## ⚙️ Configuração (Settings)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_CONTEXT_LIMIT` | `8192` | Janela total do modelo (`ModelProfile.context_limit`) |
| `DEFAULT_INPUT_BUDGET` | `6000` | Tokens para prompt (`ModelProfile.input_budget`) |
| `DEFAULT_OUTPUT_RESERVE` | `1024` | Reserva para completion (`ModelProfile.output_reserve`) |
| `skills_max_per_operation` | `2` | Quantas skills entram no prompt da operação |

## 🧪 Testes

```bash
pytest tests/test_context_budget.py -v
pytest tests/test_sufficient_context.py -v
pytest tests/test_context_recovery.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Context builder:** [docs/architecture/context-builder.md](../../../docs/architecture/context-builder.md)