# Ferramentas e segurança

Registro: `src/agent/tools/registry.py` · builtins: `src/agent/tools/builtins.py`

| ID | Função | Aprovação |
|----|--------|-----------|
| `list_dir` | Lista o diretório (pula `node_modules`, `.git`, `.venv`) | Não |
| `glob_files` | Encontra arquivos por glob | Não |
| `read_file` | Leitura dentro do `root_path`, com `offset`/`limit` | Não |
| `search_grep` | Busca regex (limite 100 hits, com `path`) | Não |
| `edit_file` | Troca um trecho único (`old_string`/`new_string`) | Não |
| `write_file` | Gravação controlada | Não |
| `make_dir` | Cria diretório | Não |
| `delete_file` | Apaga um arquivo | **Sim** |
| `move_file` | Move ou renomeia | **Sim** |
| `run_command` | Subprocess argv ou string (sem shell) | **Sim** |
| `run_script` | Executa um `.py` com `PYTHONPATH` do pacote | **Sim** |
| `run_pytest` | Testes pytest | Não |
| `git_status` | `git status --short` | Não |
| `git_diff` | Diff (cortado em 12 mil caracteres) | Não |

Nomes que o modelo costuma inventar (`ls`, `grep`, `str_replace`, `shell`, `python`, `pytest`, `rm`) apontam para a ferramenta real. Verificação aceita `pytest`, `script` e `command`.

`run_pytest` e `run_script` usam o interpretador de `python_for`: o `.venv`/`venv` do projeto, se existir, senão o Python que roda o agente. Em sistemas sem o comando `python` (macOS só tem `python3`), `run_command` troca `python` por esse interpretador. Executável inexistente não derruba o passo: volta `success: false` com `category: "configuration"`, para o orquestrador separar erro de configuração de falha de verificação.

Anexos do chat (texto longo, imagem, documento) vão para `.callidus/anexos/<tarefa>/` (a pasta legada `.agente/anexos/` continua sendo usada quando já tem arquivos da tarefa). O objetivo guarda só o caminho; o Context Builder inclui um trecho do texto e, em modelo com visão, a imagem.

Paths validados em `src/agent/security/paths.py` — traversal bloqueado.

API: `GET /tools` lista contratos.
