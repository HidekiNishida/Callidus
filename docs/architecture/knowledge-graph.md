# Grafo de conhecimento do projeto

![arquitetura](/media/icons/arquitetura.svg){width=48}

O grafo de conhecimento do projeto e o que ele indexa.

Representação persistente em SQLite (`kg_nodes`, `kg_edges`) para localizar arquivos, símbolos Python, documentos e requisitos canônicos sem carregar o repositório inteiro no prompt.

## 🏗️ Indexação

- `KnowledgeGraphService.reindex(project_id, root_path)` — scan com limite de arquivos, AST para funções/classes, arestas `contains`, `defines`, `tests`, `documents`.
- `touch_file` — atualização incremental após `write_file` no orquestrador.

## 🔌 API

- `POST /projects/{id}/knowledge/reindex`
- `GET /projects/{id}/knowledge/search?q=`
- `GET /projects/{id}/knowledge/neighbors?ref=&depth=`

## ⚙️ Uso pelo Context Builder

Símbolos mencionados no objetivo orientam leitura de trechos via `grep_symbols_in_objective` e vizinhança no grafo.

Código: [graph_service.py](/src/agent/knowledge/graph_service.py)