# Ferramentas (`tools/`) — Registro, Execução e 17 Builtins

Ferramentas determinísticas que o agente executa no filesystem/projeto autorizado. Registro central com aliases, aprovação, timeouts e observabilidade.

## Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`registry.py`](registry.py) | `ToolRegistry`, `ToolSpec`, `ToolContext`, `build_default_registry`, `canonical_tool_id`, `current_call_id` | **Registro central** — specs, handlers, aliases, execução com eventos |
| [`builtins.py`](builtins.py) | 17 handlers (`_read_file`, `_write_file`, `_edit_file`, `_search_grep`, `_run_command`, `_run_pytest`, `_run_script`, `_list_dir`, `_glob_files`, `_delete_file`, `_make_dir`, `_move_file`, `_git_status`, `_git_diff`, `_remember`, `_system_info`, `_browser`) | **Implementações reais** — filesystem, comandos, git, testes, navegador, memória |
| [`browser.py`](browser.py) | `browser_call`, `search_web` | Navegador (Playwright CDP) — navigate, snapshot, click, type, press, scroll, search, close |
| [`diffing.py`](diffing.py) | `unified_diff_text` | Diff unificado (added/removed lines) para `file.changed/created` events |

## ToolContext (Contexto de Execução)

```python
@dataclass
class ToolContext:
    project_root: str          # Raiz do projeto (segurança: resolve_under_root)
    run_id: str | None         # Para logs/eventos
    task_id: str | None        # Para logs/eventos
    memory_saver: Callable     # Tool `remember` → ProjectService.add_memory
    browser_mode: str          # "off" | "headless" | "visible"
```

## 17 Ferramentas Builtins

| ID | Descrição | Args Principais | Aprovação |
|----|-----------|-----------------|-----------|
| `read_file` | Lê arquivo (paginado) | `path`, `offset?`, `limit?` | Não |
| `write_file` | Grava arquivo (cria dirs) | `path`, `content` | Não |
| `edit_file` | Substitui trecho único | `path`, `old_string`, `new_string`, `replace_all?` | Não |
| `search_grep` | Busca regex em arquivos | `pattern`, `path?` | Não |
| `run_command` | Executa comando (argv) | `command` (list/str), `cwd?`, `timeout?`, `env?` | **Sim** |
| `run_pytest` | Executa pytest (sem bytecode) | `path?`, `timeout?` | Não |
| `run_script` | Executa .py local | `path`, `timeout?` | **Sim** |
| `list_dir` | Lista arquivos (recursivo opcional) | `path?`, `recursive?` | Não |
| `glob_files` | Encontra por glob | `pattern` | Não |
| `delete_file` | Apaga arquivo | `path` | **Sim** |
| `make_dir` | Cria diretório | `path` | Não |
| `move_file` | Move/renomeia | `from`, `to` | **Sim** |
| `git_status` | `git status --short` | — | Não |
| `git_diff` | `git diff` (stat/staged/path) | `staged?`, `stat?`, `path?` | Não |
| `remember` | Grava memória | `content`, `title?`, `scope: project\|conversation` | Não |
| `system_info` | Sistema, usuário, pasta home | — | Não |
| `browser` | Navegador (quando ligado) | `action`, `url?`, `text?`, `selector?`, `query?` | Não |

## Aliases (O que o Modelo Costuma Inventar → Real)

```python
TOOL_ALIASES = {
    "ls": "list_dir", "list_files": "list_dir", "dir": "list_dir",
    "glob": "glob_files", "find_files": "glob_files", "find": "glob_files",
    "grep": "search_grep", "search": "search_grep",
    "str_replace": "edit_file", "search_replace": "edit_file", "apply_patch": "edit_file",
    "replace_in_file": "edit_file", "edit": "edit_file",
    "delete": "delete_file", "remove_file": "delete_file", "rm": "delete_file",
    "shell": "run_command", "bash": "run_command", "exec": "run_command",
    "python": "run_script", "pytest": "run_pytest",
    "mkdir": "make_dir", "create_directory": "make_dir",
    "mv": "move_file", "rename": "move_file",
    "git": "git_status",
    "browse": "browser", "web": "browser", "open_url": "browser",
    "sysinfo": "system_info", "os_info": "system_info", "whoami": "system_info",
}
```

## TOOL_CATALOG (O que o Modelo Vê no Prompt)

```
"Ferramentas locais (use exatamente estes ids): 
list_dir, glob_files, read_file, search_grep, edit_file, write_file, 
delete_file, make_dir, move_file, run_pytest, run_script, run_command, git_status, git_diff.
edit_file: path, old_string, new_string.
read_file: path, offset e limit opcionais.
run_script executa um .py. run_command aceita command como lista ou string e exige aprovação.
delete_file e move_file exigem aprovação.
remember grava uma memória: content, title opcional e scope project ou conversation.
system_info descreve o sistema, o usuário e a pasta pessoal, em qualquer sistema operacional.
browser: action navigate, snapshot, click, type, press, scroll, search ou close.
search usa query. navigate usa url http(s). click usa text ou selector.
Não invente outros nomes."
```

## Execução (`ToolRegistry.execute`)

```python
async def execute(tool_id, ctx, args, *, approved=False):
    tool_id = canonical_tool_id(tool_id)  # resolve alias
    if tool_id not in specs: return error("ferramenta desconhecida")
    spec = specs[tool_id]
    if spec.requires_approval and not approved: return error("approval_required")
    
    call_id = uuid.uuid4().hex[:12]
    emit("tool.started", {"call_id": call_id, "tool": tool_id, "args": preview(args)})
    try:
        result = await handler(ctx, args)
    except Exception as exc:
        emit("tool.failed", {"call_id": call_id, "tool": tool_id, "error": str(exc)})
        raise
    if result.get("success"):
        emit("tool.completed", {"call_id": call_id, "tool": tool_id, "summary": summary(result)})
    else:
        emit("tool.failed", {"call_id": call_id, "tool": tool_id, "error": result.get("error")})
    return result
```

## Eventos Emitidos (Observabilidade)

- `tool.started` / `tool.completed` / `tool.failed` — call_id, tool, args (preview), duration, summary
- `file.read` / `file.changed` / `file.created` / `file.deleted` — path, diff (added/removed), sensitive flag
- `command.started` / `command.output` (streaming) / `command.completed` / `command.failed`
- `test.started` / `test.output` / `test.completed` / `test.failed`

## Segurança de Paths

Todas as ferramentas de arquivo usam `resolve_under_root(project_root, raw)` ([`../security/paths.py`](../security/paths.py)):
- Resolve caminho absoluto
- Verifica se está dentro de `project_root`
- Levanta `PathSecurityError` se tentativa de escape (`../`, symlinks fora, etc.)

## Navegador (`browser.py`)

- **Modos**: `off` (erro), `headless` (invisível), `visible` (janela Chrome via Playwright)
- **Ações**: `navigate(url)`, `snapshot()`, `click(text/selector)`, `type(text/selector)`, `press(key)`, `scroll(direction)`, `search(query)`, `close()`
- **Search**: `search_web(query)` → DuckDuckGo HTML scrape (fallback se Playwright indisponível)

## Testes

```bash
# Ferramentas builtins
pytest tests/test_tools.py -v

# Diff + resume + browser
pytest tests/test_diff_resume_browser.py -v

# Dev tools (ferramentas de desenvolvimento)
pytest tests/test_dev_tools.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Doc ferramentas:** [docs/architecture/ferramentas.md](../../../docs/architecture/ferramentas.md)