# Ferramentas e segurança

As ferramentas determinísticas: registro, execução e permissões.

Registro: `src/agent/tools/registry.py` · builtins: `src/agent/tools/builtins.py` ·
automações: `src/agent/tools/automations.py`

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

## 💬 Ferramentas de automação

O chat tem um segundo conjunto de ferramentas, para as tarefas agendadas:
`automation_create`, `automation_list`, `automation_get`, `automation_update`,
`automation_enable`, `automation_suspend`, `automation_disable`,
`automation_run_now`, `automation_test`, `automation_history`,
`automation_cancel`, `automation_delete` e `automation_supervisor_status`.

Elas **não** mexem no disco: chamam os serviços de automação
([`agent.automation.chat_service`](/src/agent/automation/chat_service.py)), que por
sua vez usam o mesmo runtime da API — mesma fonte de verdade, mesma idempotência.
O horário chega em linguagem natural («todos os dias às 9h») e é convertido em
gatilho validado pelo backend, não pelo modelo.

As duas famílias nunca se misturam: as ferramentas de automação entram sozinhas na
etapa de automação do orquestrador, e as de arquivo, na etapa de operação.
Detalhes: [automacoes.md](/docs/architecture/automacoes.md#12-automação-pela-conversa).

Durante a **operação do modelo**, o agente oferece as ferramentas ao provedor e executa o que o modelo pedir (inspeção e, se o modelo quiser, a própria escrita) — o registro continua sendo o mesmo: caminho validado, diff e aprovação. Detalhes: [ciclo-ferramentas.md](/docs/architecture/ciclo-ferramentas.md).

`run_pytest` e `run_script` usam o interpretador de `python_for`: o `.venv`/`venv` do projeto, se existir, senão o Python que roda o agente. Em sistemas sem o comando `python` (macOS só tem `python3`), `run_command` troca `python` por esse interpretador. Executável inexistente não derruba o passo: volta `success: false` com `category: "configuration"`, para o orquestrador separar erro de configuração de falha de verificação.

Anexos do chat (texto longo, imagem, documento) vão para `.callidus/anexos/<tarefa>/` (a pasta legada `.agente/anexos/` continua sendo usada quando já tem arquivos da tarefa). O objetivo guarda só o caminho; o Context Builder inclui um trecho do texto e, em modelo com visão, a imagem.

Paths validados em `src/agent/security/paths.py` — traversal bloqueado.

API: `GET /tools` lista contratos. `GET /tools/availability` diz o que falta.
`GET /tools/families` mostra a política. `GET /system/diagnose` descreve o ambiente.
`GET /skills` lista as skills instaladas.

Famílias de sistema, desktop, engenharia e autoria de skills, com a matriz do que foi
implementado e do que foi testado em cada sistema: [automacao-sistema.md](/docs/architecture/automacao-sistema.md).