# Memória (`memory/`) — Extração e Gravação (Project + Conversation)

Sistema de memória tipada com dois escopos: projeto (canônica) e conversa (contextual/execution/evidence/procedure).

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`store.py`](store.py) | `extract_memory_request(text)`, `memory_saver(args)` | **Interface** — detecta pedidos "lembre-se" + tool `remember` |
| [`__init__.py`](__init__.py) | Re-exporta | `from agent.memory import extract_memory_request` |

## 🧠 Tipos de Memória (`MemoryKind`)

| Kind | Escopo | Uso | Exemplo |
|------|--------|-----|---------|
| `CANONICAL` | Projeto | Requisitos/decisões imutáveis | "Objetivo global", "Decisão: usar FastAPI" |
| `EXECUTION` | Task/Run | Planos, tentativas, bloqueios | "Plano v3: dividir em 5 etapas" |
| `CONTEXTUAL` | Conversa | Referências a arquivos/trechos | "Arquivo principal: src/main.py" |
| `EVIDENCE` | Task | Testes, logs, comandos | "pytest passou em tests/test_api.py" |
| `PROCEDURE` | Projeto/Conv | Padrões reutilizáveis | "Como rodar testes: pytest -xvs" |

## 🧠 Extração Automática (`extract_memory_request`)

```python
# store.py
def extract_memory_request(text: str) -> tuple[str, str] | None:
    """Detecta 'lembre-se de...', 'grave na memória...', 'anote que...'"""
    patterns = [
        r"lembre[- ]se de (.+)",
        r"grave na mem[oó]ria (.+)",
        r"anote que (.+)",
        r"remember (?:that )?(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            scope = "project" if "projeto" in text.lower() else "conversation"
            return scope, m.group(1).strip()
    return None
```

**Chamado em**: `api/task_routes.py` → `create_task` (se o usuário pede para lembrar) + `tools/builtins.py` → `_remember` (tool explícita).

## 🛠️ Tool `remember` (`tools/builtins.py`)

```python
async def _remember(ctx: ToolContext, args: dict) -> dict:
    if ctx.memory_saver is None:
        return {"success": False, "error": "memória indisponível"}
    return ctx.memory_saver(args)  # args: content, title?, scope?
```

## 🧠 Gravação (`ProjectService.add_memory`)

```python
# services/project_service.py
def add_memory(self, project_id, data: MemoryCreate) -> MemoryRecordModel:
    record = MemoryRecordModel(
        project_id=project_id,
        conversation_id=data.conversation_id,  # None se scope=project
        branch_id=data.branch_id,
        task_id=data.task_id,
        kind=data.kind.value,
        title=data.title[:180],
        content=data.content,
        source_refs_json=data.source_refs,
    )
    session.add(record)
    session.flush()
    return record
```

## ⚙️ Uso no Contexto (Futuro)

- Memórias canônicas injetadas no prompt via `OperationContextBuilder` (global_rules)
- Memórias contextuais da conversa injetadas conforme relevância
- Compactação futura: nova versão com `source_refs` apontando para registros anteriores

## 🧪 Testes

```bash
# Memória + conversas + i18n
pytest tests/test_conversations_memory_i18n.py -v

# Replanejamento com memória
pytest tests/test_loose_memory_replan.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Modelo de dados:** [docs/architecture/modelo-dados.md](../../../docs/architecture/modelo-dados.md#memória)