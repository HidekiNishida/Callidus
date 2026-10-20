# Utilitários (`util/`) — Parse JSON Tolerante

![desenvolvimento](/media/icons/desenvolvimento.svg){width=48}

Utilitários compartilhados sem dependências externas.

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`json_parse.py`](json_parse.py) | `parse_json_object(text)`, `extract_json_objects(text)` | **Extração robusta** — encontra e parseia JSON válido em texto sujo (resposta do modelo) |

## 🛠️ `parse_json_object(text)` → `tuple[dict|None, str|None]`

```python
# json_parse.py
def parse_json_object(text: str) -> tuple[dict | None, str | None]:
    """
    Tenta extrair um objeto JSON do texto.
    Retorna (dict, None) se sucesso, (None, error_msg) se falha.
    """
    # 1. Tenta parse direto
    # 2. Procura primeiro '{' e último '}' 
    # 3. Tenta parse do slice
    # 4. Se falha, procura por ```json``` fence
    # 5. Retorna erro descritivo
```

**Usado em**: `orchestrator/execution/model_operation.py` → `ModelOperation.run` (parseia a resposta do modelo para `model_operation`) e `orchestrator/decomposition.py` → `plan_with_model` (parseia o plano).

## 🛠️ `extract_json_objects(text)` → `list[dict]`

```python
def extract_json_objects(text: str) -> list[dict]:
    """Extrai TODOS objetos JSON de nível superior do texto."""
    # Usa stack para balancear chaves
    # Útil quando modelo retorna múltiplos objetos
```

## 🧪 Testes

```bash
# Testado indiretamente via orquestrador
pytest tests/test_e2e_orchestrator.py -v
pytest tests/test_decomposition.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)