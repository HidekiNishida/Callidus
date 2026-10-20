# Visão (`vision/`) — Referências de Imagem para Contexto

Prepara referências a imagens (base64/data URI) quando o perfil do modelo suporta visão (`supports_vision=True`).

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`context.py`](context.py) | `ImageReference`, `validate_image_path` | **Referências** — path → base64/data URI, validação de formato/tamanho |

## 🛠️ ImageReference (`context.py`)

```python
# context.py
@dataclass
class ImageReference:
    path: str                    # Path relativo ao project_root
    mime_type: str               # "image/png", "image/jpeg", "image/webp", etc.
    data: str                    # Base64 encoded ou data URI
    width: int | None = None     # Metadados opcionais
    height: int | None = None
```

## 🧪 Validação

```python
def validate_image_path(project_root: str, raw_path: str) -> Path:
    full = resolve_under_root(project_root, raw_path)  # segurança
    if not full.is_file():
        raise FileNotFoundError(raw_path)
    mime = mimetypes.guess_type(full)[0]
    if not mime or not mime.startswith("image/"):
        raise ValueError(f"Não é imagem: {raw_path}")
    # Limite de tamanho (ex: 5MB para base64)
    if full.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Imagem muito grande (>5MB)")
    return full
```

## 🔌 Integração Futura

- `OperationContextBuilder` → detecta `task.metadata.images` → carrega via `ImageReference` → injeta no prompt (messages com `images: [base64...]`)
- `ModelProfile.supports_vision` (detectado por tokens no model_id: `-vl`, `vl:`, `vision`, `llava`, `moondream`)
- Provedores: Ollama suporta `images` no `/api/chat`; llama.cpp via OpenAI compat

## 🧪 Testes

```bash
# Ainda não há testes específicos de visão
pytest tests/test_tools.py -v  # inclui browser com snapshot (imagem)
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)