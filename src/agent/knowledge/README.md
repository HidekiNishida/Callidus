# Knowledge Graph (`knowledge/`) — Grafo de Símbolos, Imports e Arquivos

Índice incremental do código do projeto: arquivos, símbolos (classes, funções), imports e requisitos. Usado para busca semântica e navegação no contexto.

## Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`indexer.py`](indexer.py) | `index_python_file`, `extract_symbols` | **Scan AST** — visita `ast.Module` → `ClassDef`, `FunctionDef`, `Import`, `ImportFrom` |
| [`graph_service.py`](graph_service.py) | `KnowledgeGraphService` | **Persistência + API** — `reindex`, `search`, `neighbors`, `touch_file` |

## Indexador AST (`indexer.py`)

```python
def index_python_file(path: Path, project_root: Path) -> list[tuple[str, str, dict]]:
    """Retorna lista de (kind, ref, meta) para um arquivo .py"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    symbols = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append(("class", f"{module}.{node.name}", {"line": node.lineno, "docstring": ast.get_docstring(node)}))
        elif isinstance(node, ast.FunctionDef):
            symbols.append(("function", f"{module}.{node.name}", {"line": node.lineno, "args": [a.arg for a in node.args.args]}))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                symbols.append(("import", alias.name, {"line": node.lineno, "from": node.module if isinstance(node, ast.ImportFrom) else None}))
    return symbols
```

## KnowledgeGraphService (`graph_service.py`)

```python
class KnowledgeGraphService:
    def reindex(self, project_id, project_root) -> dict:
        """Varre project_root/*.py, upsert KgNode + KgEdge (imports)"""
        # 1. Limpa nodes/edges antigos do projeto
        # 2. Para cada .py: index_python_file → upsert nodes
        # 3. Para cada import: cria edge (src=file, dst=import, rel="imports")
        # 4. Retorna stats: {"files": N, "nodes": M, "edges": K}
    
    def search(self, project_id, query, limit=20) -> list[dict]:
        """Busca textual em label/ref/meta (ILIKE)"""
    
    def neighbors(self, project_id, ref, depth=1) -> list[dict]:
        """Vizinhos no grafo (imports, dependências) até depth"""
    
    def touch_file(self, project_id, project_root, rel_path) -> None:
        """Reindexa um único arquivo após write/edit/move (incremental)"""
```

## Modelo de Dados (KG)

| Tabela | Entidade | Chaves |
|--------|----------|--------|
| `kg_nodes` | `KgNodeModel` | `id`, `project_id`, `kind` (file/class/function/import/requirement), `ref` (path ou fqn), `label`, `meta_json`, `updated_at` — **unique (project_id, kind, ref)** |
| `kg_edges` | `KgEdgeModel` | `id`, `project_id`, `src_id`, `dst_id`, `rel` (imports/defines/references/covers) — **unique (project_id, src_id, dst_id, rel)** |

## API (Rotas)

| Rota | Descrição |
|------|-----------|
| `POST /projects/{id}/knowledge/reindex` | Reindexa todo o projeto (varre AST) |
| `GET /projects/{id}/knowledge/search?q=...&limit=...` | Busca textual |
| `GET /projects/{id}/knowledge/neighbors?ref=...&depth=...` | Vizinhos no grafo |

## Integração com Orquestrador

- `touch_file` chamado após `write_file`/`edit_file`/`move_file` (tools builtins)
- `guide_digest(project_root, objective)` usa `search` para achar símbolos relevantes ao objetivo
- `capability_line(model_id)` + `guide_digest` injetados no prompt de decomposição

## Testes

```bash
pytest tests/test_knowledge_graph.py -v
pytest tests/test_knowledge_imports.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Doc:** [docs/architecture/knowledge-graph.md](../../../docs/architecture/knowledge-graph.md)