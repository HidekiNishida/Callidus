# Guias (`guides/`) — Descoberta de Capacidade por Modelo

Fornece linhas de capacidade específicas do modelo e resumo de guias do projeto (AGENTS.md, READMEs) para injeção no prompt de decomposição.

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`discover.py`](discover.py) | `capability_line(model_id)`, `guide_digest(project_root, objective)` | **Descoberta** — capability line do modelo + digest de guias do projeto |

## 💡 Capability Line (`capability_line`)

```python
# discover.py
def capability_line(model_id: str) -> str:
    low = model_id.lower()
    if any(tok in low for tok in ("qwen3", "gpt-oss", "deepseek", "reason")):
        return "Este modelo suporta raciocínio (think). Use think=true para problemas complexos."
    if "llama3.2" in low or "llama3.1" in low:
        return "Llama 3.x: siga o formato JSON estrito; evite comentários fora do JSON."
    if "codellama" in low:
        return "CodeLlama: otimizado para código; use edit_file com old_string/new_string exatos."
    if "mistral" in low:
        return "Mistral: prefira respostas concisas; JSON válido obrigatório."
    return "Modelo genérico: responda SOMENTE JSON válido conforme schema."
```

## 💡 Guide Digest (`guide_digest`)

```python
# discover.py
def guide_digest(project_root: str, objective: str) -> str:
    """Lê AGENTS.md, README.md, CLAUDE.md, .cursorrules do projeto e resume."""
    guide_files = ["AGENTS.md", "README.md", "CLAUDE.md", ".cursorrules"]
    parts = []
    for fname in guide_files:
        path = Path(project_root) / fname
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            # Extrai primeiras 2000 chars + headings relevantes
            parts.append(f"=== {fname} ===\n{content[:2000]}")
    return "\n\n".join(parts) if parts else "Sem guias de projeto encontrados."
```

## 🔄 Uso no Orquestrador

### Decomposição (`orchestrator/decomposition.py`)
```python
digest = guide_digest(project_root, objective)
prompt = f"{language_instruction(language)}\n{browser_line}\nObjetivo: {objective}\n\nContexto do projeto:\n{digest}\n\n{requirements_block(requirements)}\n{capability_line(profile.model_id)}\n{TOOL_CATALOG}\n..."
```

### Fechamento (`orchestrator/closing.py`)
```python
from agent.guides.discover import capability_line, local_now_line

prompt = (
    f"{language_instruction(locale)}\n"
    f"{capability_line(profile.model_id)}\n"
    "Escreva somente a resposta para a pessoa...\n"
    f"Data e hora locais agora: {local_now_line()}.\n\n"
    f"Pedido:\n{objective[:1500]}\n\nEtapas:\n{stages}"
)
```

## 🧪 Testes

```bash
pytest tests/test_guides_and_closing.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)