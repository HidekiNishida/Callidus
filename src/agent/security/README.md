# Segurança (`security/`) — Resolução Segura de Paths

![seguranca](/media/icons/seguranca.svg){width=48}

Garante que todas as operações de arquivo fiquem dentro do `project_root` autorizado. Usado por todas as ferramentas builtins e MCP.

## 🏗️ Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`paths.py`](paths.py) | `resolve_under_root(root, raw)`, `PathSecurityError` | **Resolução segura** — normaliza, resolve symlinks, verifica se está dentro de `root` |

## 🔐 `resolve_under_root(root, raw)` → `Path`

```python
# paths.py
def resolve_under_root(root: str | Path, raw: str) -> Path:
    root = Path(root).resolve()
    candidate = (root / raw).resolve()
    
    # Verifica se candidate está dentro de root (após resolver symlinks)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PathSecurityError(f"Caminho fora do projeto: {raw}")
    
    return candidate
```

## 🧠 Proteções

| Ameaça | Como Previne |
|--------|--------------|
| Path traversal (`../../etc/passwd`) | `relative_to(root)` falha → `PathSecurityError` |
| Symlinks escapando | `.resolve()` resolve symlinks antes da checagem |
| Paths absolutos | `root / raw` força relatividade ao root |
| Null bytes / encoding | `Path` nativo lida; validação extra se necessário |

## 🛠️ Uso nas Ferramentas (`tools/builtins.py`)

```python
async def _read_file(ctx, args):
    path = args.get("path", "")
    try:
        full = resolve_under_root(ctx.project_root, path)
    except PathSecurityError as exc:
        return {"success": False, "error": str(exc)}
    # ... lê arquivo
```

Todas as 17 ferramentas builtins usam `_resolve(ctx, raw)` que chama `resolve_under_root`.

## 🔌 MCP

Servidores MCP configurados em `mcp.json` devem receber apenas paths dentro do projeto autorizado. O `McpManager` não valida paths — responsabilidade do servidor MCP (ex: `@modelcontextprotocol/server-filesystem` recebe `--path /allowed`).

## 🧪 Testes

```bash
# Segurança de paths é testada indiretamente via ferramentas
pytest tests/test_tools.py -v
pytest tests/test_dev_tools.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)