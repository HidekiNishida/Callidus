# Ferramentas e segurança

Registro: `src/agent/tools/registry.py` · builtins: `src/agent/tools/builtins.py`

| ID | Função | Aprovação |
|----|--------|-----------|
| `read_file` | Leitura dentro do `root_path` | Não |
| `write_file` | Gravação controlada | Não |
| `search_grep` | Busca regex (limite 100 hits) | Não |
| `run_command` | Subprocess argv | **Sim** (`approve_risky_tools` ou metadata) |
| `git_diff` | Resumo git diff | Não |
| `run_pytest` | Testes | Não (usa subprocess interno) |

Paths validados em `src/agent/security/paths.py` — traversal bloqueado.

API: `GET /tools` lista contratos.
