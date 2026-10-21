# Resumo do projeto — Agente de IA Local

O mapa vivo de módulos, funções e comportamentos do código.

Resumo didático e completo do projeto inteiro: **propósito, por quê, quando e onde** de cada diretório, arquivo,
classe e função, com **entradas e saídas**. Não descreve o passo a passo interno, só o necessário para entender
o funcionamento e a arquitetura.

> Este arquivo é **mantido a cada tarefa** pelo agente e verificado por `python3 scripts/resume.py check`
> (regra: [`docs/regras/resumo-projeto.md`](/docs/regras/resumo-projeto.md)). Convenção de leitura:
> `nome(params) → saída` — descrição. Métodos aparecem como `Classe.metodo(...)`.

---

## 🎯 Visão geral

**O que é:** um agente de programação que roda **na própria máquina**. Você escreve um pedido no chat
(ex.: "crie uma tela de login"), e o agente planeja, divide em tarefas pequenas, chama um modelo de linguagem
local, executa ferramentas (ler/escrever arquivos, rodar comandos e testes, navegador, MCP), verifica o
resultado e devolve uma resposta final.

**Por quê:** modelos locais pequenos têm pouca janela de contexto e erram com facilidade. Por isso a
**complexidade fica na arquitetura** (orquestrador, decomposição, verificação, persistência) e não no prompt:
o modelo é uma peça substituível, e o estado verdadeiro fica no SQLite, permitindo retomar após falhas ou
reinícios.

**Quando/onde roda:** `agente-api` sobe uma API FastAPI em `http://127.0.0.1:8765`, que também serve a interface
web estática. Um *worker* em segundo plano avança as execuções autônomas. Dados ficam em `data/agent.db`.

### Arquitetura em camadas

```mermaid
flowchart TB
  UI["web/static — interface de chat (JS puro)"] -->|HTTP JSON| API["src/agent/api — rotas FastAPI"]
  API --> SRV["services — regras de negócio<br/>(projetos, conversas, tarefas, runs, worker)"]
  API --> ORCH["orchestrator — ciclo de execução"]
  SRV --> ORCH
  ORCH --> CTX["context — monta o prompt dentro do orçamento"]
  ORCH --> PROV["providers — Ollama, llama.cpp, mock"]
  ORCH --> TOOLS["tools — arquivos, comandos, git, navegador, MCP"]
  ORCH --> VER["verification — testes e checagens"]
  ORCH --> KG["knowledge / memory / guides"]
  SRV --> PERS["persistence — SQLite + SQLAlchemy"]
  ORCH --> PERS
  DOM["domain — enums, schemas, máquina de estados"] -.-> SRV
  DOM -.-> ORCH
```

### O caminho de uma mensagem

1. **Interface** (`web/static/assets/app.js`): mostra a mensagem na hora, cria a tarefa-raiz
   (`POST /projects/{id}/tasks`) e uma execução (`POST /projects/{id}/runs`), liga o modo autônomo e dá o
   primeiro passo (`POST /runs/{id}/step`). Enquanto houver execução ativa, novos envios ficam bloqueados.
2. **API** (`src/agent/api/main.py`): valida, grava no SQLite e delega aos *services* e ao orquestrador.
3. **Orquestrador** (`src/agent/orchestrator/runner.py`): a cada passo escolhe a próxima tarefa e
   - **planeja/decompõe** objetivos em subtarefas (`planner`, `decomposition`, `atomizer`);
   - **monta o contexto** e pede ao modelo uma operação estruturada (`context`, `providers`);
   - **executa** a ferramenta escolhida (`tools`) e **verifica** (`verification`, `global_verify`);
   - **consolida** resultados no pai, **replaneja** o que falhou e escreve a **resposta final** (`closing`).
4. **Worker** (`services/autonomous_worker.py`): continua dando passos sozinho enquanto o run for autônomo.
5. **Interface** faz *polling* (`/live`, `/tasks`, `/events`) e desenha pensamentos, etapas, diffs e a resposta.

### Conceitos-chave

| Conceito | O que é |
|----------|---------|
| **Projeto / workspace** | Pasta raiz onde o agente trabalha (`ProjectModel`); conversas sem projeto usam a pasta do usuário |
| **Conversa e ramo** | Histórico do chat (`ConversationModel`); editar uma mensagem cria um **ramo** (`BranchModel`) |
| **Tarefa** | Nó de uma árvore (`TaskModel`): `objective` (pedido) → `subsystem` → `operation` (ação atômica) |
| **Estados da tarefa** | `PENDING → PLANNING → READY → RUNNING → VERIFYING → COMPLETED`, com `RETRY_PENDING`, `BLOCKED`, `FAILED`, `CANCELLED` (`domain/state_machine.py`) |
| **Run (execução)** | Uma rodada do orquestrador sobre uma tarefa-raiz (`ExecutionRunModel`): `active`, `paused`, `completed`, `failed`, `cancelled` |
| **Tentativa** | Cada chamada a modelo, ferramenta ou verificação (`OperationAttemptModel`), com limite por tarefa |
| **Evidência / contrato** | Provas de que algo funcionou (`EvidenceModel`) e critérios de aceite da tarefa (`TaskContractModel`) |
| **Memória** | Fatos lembrados por projeto ou conversa (`MemoryRecordModel`) |
| **Grafo de conhecimento** | Símbolos e imports do código do projeto (`KgNodeModel`, `KgEdgeModel`) |
| **Eventos** | Linha do tempo de tudo que aconteceu (`EventLogModel`), base dos "pensamentos" mostrados na UI |

### Stack e execução

Python 3.11+ (FastAPI, Uvicorn, SQLAlchemy 2, Pydantic v2, httpx), SQLite, JS/CSS puros na interface,
pytest nos testes. Instalação: `pip install -e ".[dev]"`; rodar: `agente-api`; testar: `pytest`.
Configuração por variáveis de ambiente / `.env` (`src/agent/config.py`).

---

---

---

---

---

---

---

## Inventário por pasta e arquivo

### `README.md`

**Propósito:** Documentação principal do repositório — visão geral, instalação, arquitetura, navegação. **Quando/onde:** ponto de entrada para humanos e agentes.

### `pyproject.toml`

**Propósito:** Metadados do pacote Python (`agente-local`), dependências, scripts (`agente-api`), config pytest.

### `notes.md`

**Propósito:** Status efêmero do Project (espelho do painel Notes do Cursor).

### `preferences.md`

**Propósito:** Preferências do usuário/projeto (estilo, convenções, ferramentas).

### `.env.example`

**Propósito:** Template de variáveis de ambiente (copiar para `.env` e ajustar).

### `.gitignore`

**Propósito:** Ignora `.venv/`, `data/`, `__pycache__/`, `.pytest_cache/`, backups, `*.bak`, `*.pyc`.

### `scripts/chat_automation_manual.py`

**Propósito:** Validação manual com o modelo real (gpt-oss:20b via Ollama).

- `_one(session, project, provider, settings, objective: str, conversation_id) -> str` — Roda uma conversa (tarefa + run) e devolve a resposta final.
- `converse(messages: list[str], *, model: str=MODEL) -> list[str]` — Roda uma sequência de conversas com o modelo local.
- `main() -> None` — Ponto de entrada: as mensagens vêm da linha de comando.

### `src/agent/automation/chat_service.py`

**Propósito:** aplicar, pelo chat, as operações do subsistema de automações.

- `AutomationChatError(RuntimeError)` — Falha de negócio na operação de automação pedida pelo chat.
- `__init__(message: str, **payload: Any) -> None` — Cria o erro com o detalhe da falha.
- `AutomationChatService` — Operações de automação disponíveis ao chat.
- `__init__(session: Session, settings: Settings | None=None, *, project_id: uuid.UUID | str | None=None, conversation_id: uuid.UUID | str | None=None) -> None` — Cria o serviço ligado a uma sessão.
- `_await_terminal(firing_id: uuid.UUID, *, timeout: float) -> None` — Espera o disparo alcançar um estado terminal.
- `_build_action(*, action_kind: str, objective: str, command: list[str] | None, script: str | None, conversation_id: str | None, objective_mode: str, model_id: str | None, provider: str | None, allow_scripts: bool, allowed_commands: list[str] | None, allowed_paths: list[str] | None) -> tuple[Any, PermissionSpec]` — Monta a ação e as permissões da automação.
- `_build_dependencies(dependencies: list[dict[str, Any]] | None) -> list[DependencySpec]` — Valida as dependências pedidas.
- `_build_trigger(*, schedule: str | None, cron: str | None, run_at: str | None, interval_seconds: int | None, timezone: str) -> TriggerSpec` — Monta o gatilho a partir do que o usuário pediu.
- `_confirmation_token(row: AutomationModel) -> str` — Token que liga a confirmação à definição apresentada.
- `_describe_execution(result: dict[str, Any]) -> str` — Texto que separa os três estados: disparo registrado, run iniciado, objetivo concluído.
- `_existing_conversation(conversation_id: str | None) -> str | None` — Conversa a associar, quando ela realmente existe no banco.
- `_find_duplicate(definition: AutomationDefinition) -> AutomationModel | None` — Procura uma automação equivalente, para não duplicar registros.
- `_present_firing(row: AutomationFiringModel) -> dict[str, Any]` — Serializa um disparo.
- `_readiness(row: AutomationModel) -> dict[str, Any]` — Verifica as dependências declaradas da automação.
- `_recent_firings(automation_id: uuid.UUID, *, limit: int=20) -> list[dict[str, Any]]` — Disparos recentes de uma automação.
- `_resolve(automation_id: str | None, query: str | None) -> AutomationModel` — Resolve a automação pedida pelo identificador ou pelo nome.
- `_resolve_timezone(timezone: str | None) -> str` — Fuso da automação: o pedido, o configurado ou o padrão documentado.
- `_select_firings(automation_id: uuid.UUID)` — Consulta base dos disparos de uma automação.
- `_summarize(row: AutomationModel, *, brief: bool=False) -> dict[str, Any]` — Resumo estruturado de uma automação (sem objeto ORM).
- `_supervisor()` — Supervisor ligado ao mesmo banco da conversa.
- `_validate_trigger(spec: TriggerSpec) -> None` — Confere que o gatilho é executável pelo runtime.
- `cancel_pending(automation_id: str) -> dict[str, Any]` — Cancela os disparos pendentes de uma automação.
- `create(*, name: str, objective: str, schedule: str | None=None, cron: str | None=None, run_at: str | None=None, interval_seconds: int | None=None, action_kind: str='callidus', command: list[str] | None=None, script: str | None=None, timezone: str | None=None, description: str | None=None, dependencies: list[dict[str, Any]] | None=None, allow_scripts: bool=False, allowed_commands: list[str] | None=None, allowed_paths: list[str] | None=None, conversation_id: str | None=None, objective_mode: str=ObjectiveMode.FROZEN.value, model_id: str | None=None, provider: str | None=None) -> dict[str, Any]` — Cria uma automação **desabilitada**, com a definição validada.
- `delete(automation_id: str, *, confirm: bool=False) -> dict[str, Any]` — Remove uma automação.
- `diagnose() -> dict[str, Any]` — Diagnóstico do runtime: automações, próximos disparos e pendências.
- `get(automation_id: str | None=None, *, query: str | None=None) -> dict[str, Any]` — Detalha uma automação, resolvendo o identificador ou o nome citado.
- `history(automation_id: str, *, limit: int=20) -> dict[str, Any]` — Lista os disparos de uma automação, do mais recente para o mais antigo.
- `list(*, state: str | None=None, query: str | None=None, limit: int=50) -> dict[str, Any]` — Lista as automações visíveis para a conversa.
- `run_now(automation_id: str, *, wait: bool=False) -> dict[str, Any]` — Executa a automação imediatamente, sem esperar o próximo horário.
- `runtime_status() -> dict[str, Any]` — Estado do runtime de automações e do serviço nativo.
- `set_state(automation_id: str, state: str, *, confirmation_token: str | None=None) -> dict[str, Any]` — Muda o estado da automação (ativar, suspender, desativar).
- `test(automation_id: str, *, execute: bool=False) -> dict[str, Any]` — Verifica a prontidão da automação e, opcionalmente, dispara um teste.
- `update(automation_id: str, *, name: str | None=None, description: str | None=None, objective: str | None=None, schedule: str | None=None, cron: str | None=None, run_at: str | None=None, interval_seconds: int | None=None, timezone: str | None=None, dependencies: list[dict[str, Any]] | None=None, missed_policy: str | None=None, confirm: bool=False) -> dict[str, Any]` — Altera uma automação existente.
- `_heartbeat_is_fresh(heartbeat: dict[str, Any]) -> bool` — Diz se o batimento do runtime é recente.
- `_local_label(moment: datetime | None, timezone: str) -> str | None` — Instante no fuso local, em texto.
- `_normalize(text: str) -> str` — Texto em minúsculas e sem acentos, para comparar nomes.
- `_parse_instant(value: str, timezone: str) -> datetime` — Converte um texto de instante em datetime com fuso.
- `_uuid_or_none(value: Any) -> uuid.UUID | None` — Converte um valor em UUID, tolerando ausência e texto inválido.

### `src/agent/automation/intent.py`

**Propósito:** reconhecer quando o pedido da conversa é sobre tarefas agendadas.

- `is_automation_request(text: str, *, previous: list[str] | None=None) -> bool` — Diz se o pedido é sobre tarefas agendadas.
- `is_confirmation(text: str) -> bool` — Diz se o texto é uma confirmação curta de algo já apresentado.
- `looks_like_schedule(text: str) -> bool` — Diz se o texto carrega uma expressão de horário ou recorrência.
- `normalize_text(text: str) -> str` — Texto em minúsculas e sem acentos, para comparação tolerante.

### `src/agent/automation/natural.py`

**Propósito:** entender horários, datas e recorrências escritos em linguagem natural.

- `ScheduleIntent` — Resultado da interpretação de um texto de agendamento.
- `needs_clarification() -> bool` — Diz se falta informação para o usuário.
- `resolved() -> bool` — Diz se o texto virou um gatilho utilizável.
- `_amount(text: str) -> float` — Valor numérico de um número escrito por extenso ou em dígitos.
- `_cron_dow(weekday: int) -> int` — Converte o dia da semana do Python (0 = segunda) para o do cron (0 = domingo).
- `_day_of_month(text: str) -> int | None` — Dia do mês citado no texto ("dia 15", "15 de março").
- `_format_local(moment: datetime, timezone: str) -> str` — Formata um instante no fuso local, para a prévia e para a resposta ao usuário.
- `_human_interval(seconds: int) -> str` — Duração em linguagem legível.
- `_match_interval(text: str) -> int | None` — Procura uma recorrência de intervalo fixo no texto.
- `_match_next_weekday(text: str, today: date, current: date | None) -> tuple[date | None, str]` — Reconhece "na próxima segunda": uma ocorrência, não uma recorrência.
- `_match_recurrence(text: str) -> tuple[str | None, str]` — Reconhece a recorrência do texto.
- `_match_relative_date(text: str, reference: datetime) -> tuple[date | None, tuple[int, int] | None, str]` — Procura uma data relativa ou absoluta no texto.
- `_match_time(text: str) -> tuple[int, int] | None` — Procura um horário de parede no texto ("9h", "8h30", "14:00", "às 9").
- `_next_weekday(today: date, weekday: int) -> date` — Próxima data de um dia da semana (o próprio dia conta, quando é hoje).
- `_now_in(timezone: str) -> datetime` — Instante atual no fuso informado.
- `_remove(text: str, pattern: re.Pattern[str]) -> tuple[str, str | None]` — Separa um trecho do texto, devolvendo o resto e o trecho encontrado.
- `_strip_accents(text: str) -> str` — Remove acentos e baixa a caixa, para comparar texto em português.
- `_weekday_from(text: str) -> int | None` — Dia da semana citado no texto.
- `describe_cron(expression: str) -> str` — Descreve uma expressão cron em português, quando o padrão é reconhecível.
- `describe_trigger(trigger: TriggerSpec | None, *, timezone: str | None=None) -> str` — Descreve um gatilho em linguagem legível.
- `parse_schedule(text: str, *, now: datetime | None=None, timezone: str | None=None) -> ScheduleIntent` — Interpreta um pedido de horário escrito em linguagem natural.

### `src/agent/orchestrator/execution/automation_operation.py`

**Propósito:** executar a etapa de automação — o modelo fala com as ferramentas de tarefas agendadas.

- `AutomationOperation` — Etapa de automação: o modelo opera as ferramentas de tarefas agendadas.
- `__init__(executor: Any) -> None` — Guarda o executor responsável pela etapa.
- `_context_block(project: Any, task: Any) -> str` — Contexto que o modelo precisa para resolver referências ("essa automação").
- `_conversation_history(task: Any, *, limit: int=5) -> list[str]` — Últimas mensagens da conversa, para resolver «esta tarefa».
- `_existing_automations(project: Any) -> list[str]` — Resumo das automações do projeto, com identificador e estado.
- `_runtime()` — Colaboradores da execução (sessão, configurações, ferramentas).
- `run(run: Any, project: Any, task: Any, config: dict, root_path: str, ctx: Any) -> dict[str, Any]` — Executa a etapa de automação e devolve o desfecho.
- `_automation_tool_ids() -> tuple[str, ...]` — Identificadores das ferramentas de automação.
- `_compose(outcome: ToolLoopOutcome, results: list[dict[str, Any]]) -> str` — Monta o texto entregue ao usuário a partir do estado real.

### `src/agent/tools/automations.py`

**Propósito:** expor ao modelo as operações de automação como ferramentas do chat.

- `_call(ctx: ToolContext, func, *args, **kwargs) -> dict[str, Any]` — Executa uma operação do serviço e devolve o resultado no formato da ferramenta.
- `_cancel(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Cancela os disparos pendentes de uma automação.
- `_create(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Cria uma automação desabilitada, a partir de um pedido em linguagem natural.
- `_delete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Remove uma automação, exigindo confirmação.
- `_disable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Desativa uma automação.
- `_enable(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Ativa uma automação, exigindo o token da prévia confirmada.
- `_fail(exc: AutomationChatError) -> dict[str, Any]` — Transforma um erro de negócio no resultado que o modelo recebe.
- `_get(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Detalha uma automação.
- `_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Lista os disparos de uma automação.
- `_list(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Lista as automações do projeto.
- `_one_line(result: dict[str, Any]) -> str` — Resumo de uma linha do resultado.
- `_opt_int(value: Any) -> int | None` — Inteiro de um argumento, ignorando valores vazios.
- `_opt_list(value: Any) -> list[str] | None` — Lista de textos de um argumento.
- `_opt_objects(value: Any) -> list[dict[str, Any]] | None` — Lista de objetos de um argumento.
- `_opt_text(value: Any) -> str | None` — Texto de um argumento, ignorando valores vazios.
- `_render_automation(automation: dict[str, Any]) -> str` — Texto de uma automação.
- `_render_diagnostics(report: dict[str, Any]) -> str` — Texto do diagnóstico do supervisor.
- `_run_now(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Executa a automação imediatamente.
- `_schema(properties: dict[str, Any], required: list[str] | None=None) -> dict[str, Any]` — Monta um JSON Schema de objeto para o argumento de uma ferramenta.
- `_service(ctx: ToolContext) -> AutomationChatService` — Serviço de automações ligado ao contexto da ferramenta.
- `_supervisor_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Estado do runtime de automações e diagnóstico do supervisor.
- `_suspend(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Suspende uma automação.
- `_test(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Verifica a prontidão de uma automação (e só executa quando pedido).
- `_update(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]` — Altera uma automação existente.
- `_with_content(result: dict[str, Any]) -> dict[str, Any]` — Acrescenta ao resultado o texto que o modelo lê.
- `register_all(registry: ToolRegistry) -> None` — Registra no registro as ferramentas de automação.
- `render_result(result: dict[str, Any]) -> str` — Texto que o modelo lê: os fatos da operação, sem ruído.

### `test_server.py`

**Propósito:** Teste manual rápido do servidor (inicia uvicorn, faz requests básicos).

### `test_step.py`

**Propósito:** Teste manual de um step do orquestrador.

### `resume.md`

**Propósito:** Resumo vivo do projeto inteiro — propósito, quando/onde, entradas e saídas de cada diretório, arquivo, classe e função. Verificado por `scripts/resume.py check` a cada tarefa.

## `.cursor/`

**Propósito:** Configuração do Cursor (regras, hooks e inventário do resume) — lida pelo Cursor ao abrir o projeto.

- Subpasta: [.cursor/hooks/](/.cursor/hooks/)
- Subpasta: [.cursor/rules/](/.cursor/rules/)
- Arquivo: [hooks.json](/.cursor/hooks.json)
- Arquivo: [CALLIDUS_AUDITORIA.md](/.cursor/CALLIDUS_AUDITORIA.md)
- Arquivo: [CALLIDUS_DESCOBERTAS.md](/.cursor/CALLIDUS_DESCOBERTAS.md)
- Arquivo: [CALLIDUS_CHECKPOINT.md](/.cursor/CALLIDUS_CHECKPOINT.md)

### `.cursor/CALLIDUS_AUDITORIA.md`

**Propósito:** escopo, inventário de telas e critérios da auditoria frontend/backend.

### `.cursor/CALLIDUS_DESCOBERTAS.md`

**Propósito:** evidências, causas e decisões técnicas da auditoria.

### `.cursor/CALLIDUS_CHECKPOINT.md`

**Propósito:** checkpoint da auditoria integral — progresso, evidências de testes e pendências E2E/Ollama.

## `.cursor/hooks/`

**Propósito:** Hooks do Cursor executados no fim de cada resposta do agente.

- Arquivo: [resume-check.sh](/.cursor/hooks/resume-check.sh)

### `.cursor/hooks/resume-check.sh`

**Propósito:** Script chamado pelo hook `stop` — roda `python3 scripts/resume.py check` e alerta se o resumo ficou para trás.

## `.cursor/rules/`

**Propósito:** Regras sempre aplicadas pelo Cursor neste repositório.

- Arquivo: [resume.mdc](/.cursor/rules/resume.mdc)

### `.cursor/rules/resume.mdc`

**Propósito:** Regra `alwaysApply` que exige `resume.md` sincronizado a cada tarefa (check → faltando → carimbar).

### `.cursor/hooks.json`

**Propósito:** Configuração de hooks do Cursor (ex.: `stop` hook roda `resume-check.sh`). **Quando/onde:** disparado automaticamente pelo Cursor.

## `data/`

**Propósito:** Dados de runtime (gitignored): SQLite `agent.db`, `mcp.json`, logs e anexos.

- Arquivo: [README.md](/data/README.md)
- Arquivo: [mcp.example.json](/data/mcp.example.json)

### `data/README.md`

**Propósito:** Índice da pasta `data/` (runtime gitignored).

### `data/mcp.example.json`

**Propósito:** Template de configuração MCP stdio (copiar para `data/mcp.json`).

## `docs/`

**Propósito:** Documentação técnica do projeto (arquitetura, regras e contexto).

- Subpasta: [docs/architecture/](/docs/architecture/)
- Subpasta: [docs/regras/](/docs/regras/)
- Arquivo: [README.md](/docs/README.md)
- Arquivo: [project-context.md](/docs/project-context.md)

## `docs/architecture/`

**Propósito:** Documentos de arquitetura do runtime do agente.

- Arquivo: [README.md](/docs/architecture/README.md)
- Arquivo: [context-builder.md](/docs/architecture/context-builder.md)
- Arquivo: [diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md)
- Arquivo: [execucao-autonoma.md](/docs/architecture/execucao-autonoma.md)
- Arquivo: [execucao-local.md](/docs/architecture/execucao-local.md)
- Arquivo: [ferramentas.md](/docs/architecture/ferramentas.md)
- Arquivo: [frontend.md](/docs/architecture/frontend.md)
- Arquivo: [knowledge-graph.md](/docs/architecture/knowledge-graph.md)
- Arquivo: [limitacoes.md](/docs/architecture/limitacoes.md)
- Arquivo: [maquina-estados.md](/docs/architecture/maquina-estados.md)
- Arquivo: [mcp.md](/docs/architecture/mcp.md)
- Arquivo: [modelo-dados.md](/docs/architecture/modelo-dados.md)
- Arquivo: [requisitos-verificacao-progresso.md](/docs/architecture/requisitos-verificacao-progresso.md)
- Arquivo: [skills-estrategia.md](/docs/architecture/skills-estrategia.md)
- Arquivo: [estrategia-resolucao.md](/docs/architecture/estrategia-resolucao.md)
- Arquivo: [ux-ui.md](/docs/architecture/ux-ui.md)
- Arquivo: [visao-geral.md](/docs/architecture/visao-geral.md)

### `docs/architecture/README.md`

**Propósito:** Índice da pasta `architecture/` (documentos técnicos do runtime).

### `docs/architecture/automacao-sistema.md`

**Propósito:** Automação de sistema, desktop, engenharia e skills: política de risco, matriz de plataforma e como testar.

### `docs/architecture/context-builder.md`

**Propósito:** Orçamento de tokens, componentes do prompt, compactação, `ContextBudgetError`.

### `docs/architecture/diagnostico-evolucao.md`

**Propósito:** Diagnóstico de problemas históricos e evolução da arquitetura.

### `docs/architecture/execucao-autonoma.md`

**Propósito:** Worker autônomo, loop background, modo autônomo, replanejamento.

### `docs/architecture/execucao-local.md`

**Propósito:** Instalação, variáveis de ambiente, padrões (Ollama), conversas, memória, UI, MCP, testes.

### `docs/architecture/ferramentas.md`

**Propósito:** Catálogo de ferramentas builtins, aliases, aprovação, segurança de paths.

### `docs/architecture/frontend.md`

**Propósito:** SPA IDE-like (layout, componentes, polling, SSE, diff, live board).

### `docs/architecture/knowledge-graph.md`

**Propósito:** Grafo de conhecimento (AST indexer, nodes/edges, search, neighbors).

### `docs/architecture/limitacoes.md`

**Propósito:** Limitações conhecidas do agente (contexto, verificação, replanejamento, etc.).

### `docs/architecture/maquina-estados.md`

**Propósito:** Machine de estados `TaskStatus` + transições permitidas (Mermaid).

### `docs/architecture/mcp.md`

**Propósito:** Integração MCP stdio (config, discover, call, transport).

### `docs/architecture/orquestracao-qualidade.md`

**Propósito:** Contrato de qualidade, disposição seletiva (executar, investigar, decompor, replanejar) e evento `work.explained` no feed.

### `docs/architecture/modelo-dados.md`

**Propósito:** 14 entidades SQLite + campos essenciais + relações.

### `docs/architecture/requisitos-verificacao-progresso.md`

**Propósito:** Requisitos rastreáveis, validação de plano, verificação independente, progresso real, estagnação, limites, pausa/retomada.

### `docs/architecture/estrategia-linguistica.md`

**Propósito:** separar idioma do pedido, idioma operacional e idioma da interface, com modos `native`, `english_operational` e `auto`.

### `docs/architecture/estrategia-resolucao.md`

**Propósito:** explicar como o Callidus reconhece estagnação, escolhe uma abordagem diferente, aplica limites coerentes e registra o que aprendeu. **Quando/onde:** leitura de referência para quem quiser entender ou investigar a decisão do agente diante de uma falha.

### `docs/architecture/skills-estrategia.md`

**Propósito:** Arquitetura das skills sob demanda, da estratégia profissional, da decomposição recursiva e do ciclo de recuperação da verificação.

### `docs/architecture/ux-ui.md`

**Propósito:** Guia de UX/UI da interface web (layout, estados, interações).

### `docs/architecture/visao-geral.md`

**Propósito:** Visão macro da arquitetura (camadas, fases, ADRs, stack).

## `docs/regras/`

**Propósito:** Regras operacionais para agentes (hub em `README.md`).

- Arquivo: [README.md](/docs/regras/README.md)
- Arquivo: [ativos-visuais.md](/docs/regras/ativos-visuais.md)
- Arquivo: [autoaperfeicoamento.md](/docs/regras/autoaperfeicoamento.md)
- Arquivo: [checklists-tarefas.md](/docs/regras/checklists-tarefas.md)
- Arquivo: [commits.md](/docs/regras/commits.md)
- Arquivo: [documentacao.md](/docs/regras/documentacao.md)
- Arquivo: [mcps.md](/docs/regras/mcps.md)
- Arquivo: [navegacao-agentes.md](/docs/regras/navegacao-agentes.md)
- Arquivo: [organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md)
- Arquivo: [principios.md](/docs/regras/principios.md)
- Arquivo: [readmes-pastas.md](/docs/regras/readmes-pastas.md)
- Arquivo: [resumo-projeto.md](/docs/regras/resumo-projeto.md)
- Arquivo: [validacoes-testes.md](/docs/regras/validacoes-testes.md)
- Arquivo: [verificacao-final.md](/docs/regras/verificacao-final.md)

### `docs/regras/README.md`

**Propósito:** Hub das regras operacionais para agentes (como trabalhar no repo).

### `docs/regras/ativos-visuais.md`

**Propósito:** Uso de SVGs/icons nos docs (pasta `media/icons/`, referências Markdown).

### `docs/regras/autoaperfeicoamento.md`

**Propósito:** Processo de auto-aperfeiçoamento do agente (feedback loops, skills, memory).

### `docs/regras/checklists-tarefas.md`

**Propósito:** Formato de checklists em `internal/tarefas/` (título, passos, critérios, status).

### `docs/regras/commits.md`

**Propósito:** Convenção de commits em português (tipo, escopo, descrição).

### `docs/regras/documentacao.md`

**Propósito:** Padrões de documentação técnica (formato, diagramas, tabelas, navegação).

### `docs/regras/mcps.md`

**Propósito:** Regras para configuração e uso de servidores MCP no projeto.

### `docs/regras/navegacao-agentes.md`

**Propósito:** Como agentes navegam no repositório (links, convenções, context).

### `docs/regras/organizacao-arquivos.md`

**Propósito:** Organização de arquivos no repo (onde colocar cada tipo de artefato).

### `docs/regras/principios.md`

**Propósito:** Princípios fundamentais do projeto (complexidade na arquitetura, estado no SQLite, etc.).

### `docs/regras/readmes-pastas.md`

**Propósito:** Regra: toda pasta com código/docs deve ter `README.md` local (índice + links).

### `docs/regras/resumo-projeto.md`

**Propósito:** Regra do resumo vivo: o que o `resume.md` contém, o formato exigido pelo verificador e o protocolo de sincronia a cada tarefa.

### `docs/regras/validacoes-testes.md`

**Propósito:** Regras de validação e testes (pytest, cobertura, evidências).

### `docs/regras/verificacao-final.md`

**Propósito:** Checklist de verificação final antes de commit (build, testes, docs, resume.md).

### `docs/README.md`

**Propósito:** Índice da pasta `docs/` → `project-context.md`, `regras/`, `architecture/`.

### `docs/project-context.md`

**Propósito:** Metas, restrições e convenções do projeto (hub para agentes Cursor).

## `internal/`

**Propósito:** Trabalho interno do agente (checklists de tarefa e evidências).

- Subpasta: [internal/tarefas/](/internal/tarefas/)
- Arquivo: [README.md](/internal/README.md)

## `internal/tarefas/`

**Propósito:** Checklists das atividades — um arquivo por tarefa.

### `internal/README.md`

**Propósito:** Índice da pasta `internal/` (trabalho interno, checklists, evidências).

## `media/`

**Propósito:** Assets visuais (ícones SVG) usados nos documentos Markdown.

- Subpasta: [media/icons/](/media/icons/)

## `media/icons/`

**Propósito:** Ícones SVG referenciados pelos documentos.

## `scripts/`

**Propósito:** Scripts operacionais (backup do banco, correções de instalação, verificação do resume).

- Arquivo: [README.md](/scripts/README.md)
- Arquivo: [backup-data.sh](/scripts/backup-data.sh)
- Arquivo: [fix-python314-editable.py](/scripts/fix-python314-editable.py)
- Arquivo: [resume.py](/scripts/resume.py)
- Arquivo: [audit_ollama_smoke.sh](/scripts/audit_ollama_smoke.sh)

### `scripts/audit_ollama_smoke.sh`

**Propósito:** smoke E2E via API — conversa, tarefa e run com `meu_ollama` e `gpt-oss:20b` (modelo na config da run, sem alterar `providers.yaml`).

### `scripts/README.md`

**Propósito:** Índice da pasta `scripts/` (backup-data.sh, fix-python314-editable.py).

### `scripts/backup-data.sh`

**Propósito:** Backup do SQLite `data/agent.db` → `backups/agent-YYYYMMDD-HHMMSS.db`.

### `scripts/fix-python314-editable.py`

**Propósito:** Corrige editable install no Python 3.14+ (remove `.pth` com prefixo `_`).

- `main() -> None` — Entry point do script — remove arquivos `.pth` com prefixo `_` do site-packages, corrigindo a instalação editável do pacote em Python 3.14+. Executado manualmente quando o `pip install -e .` falha.

- `_site_packages() → Path` — Devolve o caminho do site-packages do virtualenv em uso.
- `_unhide(path) → None` — Remove a flag UF_HIDDEN (macOS) do arquivo, se houver.
- `_write_pth(site_packages) → Path` — Grava o .pth com o caminho de src/ e devolve o arquivo criado.
- `_write_symlink(site_packages) → Path` — Link simbólico `site-packages/agent` → `src/agent`.
### `scripts/resume.py`

**Propósito:** Valida e carimba `resume.md`.

- `Item` — dataclass imutável representando um item do inventário (dir | file | sym) com path, name e signature.
- `Item.key() -> str` — Chave única do item — `sym:path::nome(assinatura)` ou `dir:path/` ou `file:path`.
- `Item.short() -> str` — Nome curto para exibição — último segmento do path.
- `_py_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str` — Extrai assinatura de função/método Python (parâmetros sem self/cls + retorno).
- `cmd_carimbar() -> int` — Comando `carimbar` — atualiza `.cursor/resume-inventario.json` com hash atual (recusa se ainda faltar descrição).
- `cmd_check() -> int` — Comando `check` — verifica itens sem descrição no `resume.md`.
- `cmd_faltando() -> int` — Comando `faltando` — mostra esqueleto do que falta descrever.
- `cmd_hook() -> int` — Comando `hook` — executa check no pre-commit/stop hook.
- `describe(missing: list[Item], added: list[str], removed: list[str], limit: int=40) -> str` — Formata relatório de itens faltando/adicionados/removidos.
- `file_sections(text: str) -> dict[str, str]` — Parseia `resume.md` em seções por cabeçalho `##` / `###`.
- `inventory(files: list[str] | None=None) -> list[Item]` — Gera inventário de dirs/files/syms do projeto.
- `js_symbols(path: str, source: str) -> list[Item]` — Extrai símbolos JavaScript/TypeScript (funções, classes, exports) via regex.
- `load_state() -> list[str]` — Carrega estado anterior do `.cursor/resume-inventario.json`.
- `main(argv: list[str]) -> int` — Entry point do script — remove `.pth` com prefixo `_` do site-packages (corrige editable install no Python 3.14+).
- `missing_items(items: list[Item], text: str) -> list[Item]` — Compara inventário com seções do `resume.md` — retorna itens sem descrição.
- `project_files() -> list[str]` — Lista arquivos do projeto (respeita `.gitignore`, ignora `.venv`, `__pycache__`, etc.).
- `python_symbols(path: str, source: str) -> list[Item]` — Extrai símbolos Python (funções, classes, methods) via `ast.parse`.
- `report() -> tuple[list[Item], list[str], list[str]]` — Gera relatório completo: (missing, added, removed) comparando inventário atual vs estado salvo.
- `skeleton(missing: list[Item]) -> str` — Gera esqueleto markdown dos itens faltando (para `faltando`).

## `skills/`

**Propósito:** Catálogo editável de Skills do agente — a fonte de verdade das competências profissionais.

- Arquivo: [README.md](/skills/README.md)
- Arquivo: [debugging-root-cause.md](/skills/debugging-root-cause.md)
- Arquivo: [refactoring-clean-code.md](/skills/refactoring-clean-code.md)
- Arquivo: [software-engineering.md](/skills/software-engineering.md)
- Arquivo: [system-architecture.md](/skills/system-architecture.md)
- Arquivo: [technical-writing.md](/skills/technical-writing.md)
- Arquivo: [testing-quality-assurance.md](/skills/testing-quality-assurance.md)

### `skills/README.md`

**Propósito:** Índice da pasta `skills/` com catálogo de skills disponíveis.

### `skills/debugging-root-cause.md`

**Propósito:** Skill de depuração sistemática e análise de causa raiz (diagnóstico metódico, correção cirúrgica, não-regressão).

### `skills/refactoring-clean-code.md`

**Propósito:** Skill de refatoração e código limpo (estrutura, legibilidade, manutenibilidade sem alterar comportamento).

### `skills/software-engineering.md`

**Propósito:** Skill de engenharia de software e implementação modular (código robusto, tipagem, compatibilidade).

### `skills/system-architecture.md`

**Propósito:** Skill de arquitetura de sistemas e decomposição (fronteiras, contratos, separação de responsabilidades).

### `skills/technical-writing.md`

**Propósito:** Skill de documentação técnica e comunicação estruturada (sincronizada com o código real).

### `skills/testing-quality-assurance.md`

**Propósito:** Skill de garantia de qualidade e testes independentes (verificações determinísticas, critérios de aceite).

## `src/`

**Propósito:** Raiz do código-fonte do pacote instalável `agente-local`.

- Subpasta: [src/agent/](/src/agent/)
- Arquivo: [README.md](/src/README.md)

## `src/agent/`

**Propósito:** Núcleo do Agente de IA Local: API, domínio, persistência, orquestrador, ferramentas, provedores, contexto, skills, verificação e utilitários.

- Subpasta: [src/agent/api/](/src/agent/api/)
- Subpasta: [src/agent/context/](/src/agent/context/)
- Subpasta: [src/agent/domain/](/src/agent/domain/)
- Subpasta: [src/agent/guides/](/src/agent/guides/)
- Subpasta: [src/agent/i18n/](/src/agent/i18n/)
- Subpasta: [src/agent/knowledge/](/src/agent/knowledge/)
- Subpasta: [src/agent/mcp/](/src/agent/mcp/)
- Subpasta: [src/agent/memory/](/src/agent/memory/)
- Subpasta: [src/agent/observability/](/src/agent/observability/)
- Subpasta: [src/agent/orchestrator/](/src/agent/orchestrator/)
- Subpasta: [src/agent/persistence/](/src/agent/persistence/)
- Subpasta: [src/agent/providers/](/src/agent/providers/)
- Subpasta: [src/agent/remote/](/src/agent/remote/)
- Subpasta: [src/agent/automation/actions/](/src/agent/automation/actions/)
- Subpasta: [src/agent/automation/service/](/src/agent/automation/service/)
- Subpasta: [src/agent/automation/triggers/](/src/agent/automation/triggers/)
- `lab/` — pasta do projeto (ver o README da pasta).
- `src/agent/automation/` — pasta do projeto (ver o README da pasta).
- `src/agent/automation/actions/` — pasta do projeto (ver o README da pasta).
- `src/agent/automation/service/` — pasta do projeto (ver o README da pasta).
- `src/agent/automation/triggers/` — pasta do projeto (ver o README da pasta).
- `web/static/assets/app/` — pasta do projeto (ver o README da pasta).
- `web/static/assets/app/components/` — pasta do projeto (ver o README da pasta).
- Subpasta: [src/agent/security/](/src/agent/security/)
- Subpasta: [src/agent/services/](/src/agent/services/)
- Subpasta: [src/agent/skills/](/src/agent/skills/)
- Subpasta: [src/agent/tools/](/src/agent/tools/)
- Subpasta: [src/agent/util/](/src/agent/util/)
- Subpasta: [src/agent/verification/](/src/agent/verification/)
- Subpasta: [src/agent/vision/](/src/agent/vision/)
- Arquivo: [README.md](/src/agent/README.md)
- Arquivo: [__init__.py](/src/agent/__init__.py)
- Arquivo: [config.py](/src/agent/config.py)

- Subpasta: [src/agent/desktop/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/)
- Subpasta: [src/agent/engineering/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/)
- Subpasta: [src/agent/system/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/)
## `src/agent/system/`

**Propósito:** Automação do sistema operacional: adaptadores por plataforma, inventário de processos, aplicativos e diagnóstico do ambiente.

- Subpasta: [src/agent/system/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/)
- Arquivo: [__init__.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/__init__.py)
- Arquivo: [adapters.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/adapters.py)
- Arquivo: [apps.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/apps.py)
- Arquivo: [platform_info.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/platform_info.py)
- Arquivo: [processes.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/system/processes.py)
- Arquivo: [README.md](/src/agent/system/README.md)
## `src/agent/engineering/`

**Propósito:** Caixa de ferramentas de engenharia de software: descoberta de projeto, leitura do Git e execução de verificações de qualidade.

- Subpasta: [src/agent/engineering/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/)
- Arquivo: [__init__.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/__init__.py)
- Arquivo: [discovery.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/discovery.py)
- Arquivo: [git.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/git.py)
- Arquivo: [quality.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/engineering/quality.py)
- Arquivo: [README.md](/src/agent/engineering/README.md)
## `src/agent/desktop/`

**Propósito:** Automação de desktop do agente: tela, entrada (mouse e teclado) e janelas, com um adaptador por sistema operacional.

- Subpasta: [src/agent/desktop/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/)
- Arquivo: [__init__.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/__init__.py)
- Arquivo: [capabilities.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/capabilities.py)
- Arquivo: [input.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/input.py)
- Arquivo: [windows.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/desktop/windows.py)
- Arquivo: [accessibility.py](/src/agent/desktop/accessibility.py)
- Arquivo: [README.md](/src/agent/desktop/README.md)
## `src/agent/api/`

**Propósito:** Rotas FastAPI (REST e SSE) e dependências da aplicação.

- Arquivo: [README.md](/src/agent/api/README.md)
- Arquivo: [__init__.py](/src/agent/api/__init__.py)
- Arquivo: [agent_routes.py](/src/agent/api/agent_routes.py)
- Arquivo: [automation_routes.py](/src/agent/api/automation_routes.py)
- Arquivo: [conversation_routes.py](/src/agent/api/conversation_routes.py)
- Arquivo: [deps.py](/src/agent/api/deps.py)
- Arquivo: [live_view.py](/src/agent/api/live_view.py)
- Arquivo: [main.py](/src/agent/api/main.py)
- Arquivo: [observe_routes.py](/src/agent/api/observe_routes.py)
- Arquivo: [presenters.py](/src/agent/api/presenters.py)
- Arquivo: [project_routes.py](/src/agent/api/project_routes.py)
- Arquivo: [provider_routes.py](/src/agent/api/provider_routes.py)
- Arquivo: [run_routes.py](/src/agent/api/run_routes.py)
- Arquivo: [system_routes.py](/src/agent/api/system_routes.py)
- Arquivo: [task_routes.py](/src/agent/api/task_routes.py)

### `AGENTS.md`

**Propósito:** Regras de engenharia do Callidus — cabeçalho padrão, docstrings, SOLID pragmático, design patterns, organização modular, contratos que não podem quebrar, testes, documentação hierárquica e sincronização obrigatória. **Quando/onde:** fonte canônica lida por qualquer agente antes de escrever código.

### `docs/architecture/decisoes-arquitetura.md`

**Propósito:** Registro das decisões de arquitetura (ADR) — ciclo × execução, API por assunto, verificação independente, SQLite como fonte da verdade e modelo substituível. **Quando/onde:** ao propor uma mudança estrutural.

### `scripts/check_markdown.py`

**Propósito:** conferir a integridade estrutural dos documentos Markdown (título, hierarquia de cabeçalhos, blocos de código, tabelas e diagramas Mermaid). **Quando/onde:** ao mexer em documentação.

- `analyse(path) → list[str]` — Analisa um documento Markdown e devolve os problemas encontrados.
- `main(argv) → int` — Analisa os documentos indicados e imprime o resultado.

- `_targets(paths) → list[Path]` — Arquivos Markdown a verificar.
- `_headings(lines) → list[tuple[int, str, int]]` — Cabeçalhos do documento, na ordem em que aparecem.
- `_duplicate_siblings(headings) → list[tuple[str, int, int]]` — Títulos de seção repetidos entre irmãos.
- `_mermaid_problems(rel, lines) → list[str]` — Problemas nos diagramas Mermaid do documento.
### `scripts/check_references.py`

**Propósito:** conferir que os documentos apontam para arquivos e símbolos que realmente existem no código. **Quando/onde:** ao mexer em documentação que cita caminhos, endpoints ou funções.

- `main(argv) → int` — Verifica as referências da documentação contra o código.

- `_modulos() → dict[str, set[str]]` — Índice de símbolos por módulo Python do projeto.
- `_caminhos_documentados() → set[str]` — Caminhos de arquivo citados na documentação (para resolver relativos).
- `_candidatos(texto) → list[tuple[str, str]]` — Extrai (tipo, valor) das referências de um trecho entre crases.
- `_avaliar(tipo, valor, arquivo, rel, linha, modulos, caminhos, problemas) → None` — Confere uma referência e registra o problema, se houver.
### `scripts/check_imports.py`

**Propósito:** Conferir que uma alteração não removeu importações nem definições de símbolos do código anterior. **Quando/onde:** depois de refatorações e movimentações de arquivo.

- `symbols_of(source) → tuple[set[str], set[str]] | None` — Importações e definições de um código Python.
- `compare() → list[str]` — Compara cada arquivo Python alterado com a versão no HEAD.
- `main(argv) → int` — Executa a comparação e imprime o resultado.

- `_imports(tree) → set[str]` — Módulos importados por uma árvore sintática.
- `_defined(tree) → set[str]` — Nomes de nível superior definidos por uma árvore sintática.
- `_head_source(path) → str | None` — Conteúdo da versão do arquivo no commit HEAD.
- `_changed_files() → list[str]` — Arquivos Python alterados na árvore de trabalho (versionados ou novos).
- `_defined_everywhere() → set[str]` — Nomes definidos em qualquer módulo Python do repositório.
### `scripts/check_code_drift.py`

**Propósito:** Detectar se a edição de um arquivo Python alterou código além de comentários e docstrings. **Quando/onde:** auditoria final de uma mudança que só deveria ter mexido em documentação.

- `stripped_tree(source) → str | None` — Árvore sintática sem docstrings, em forma textual comparável.
- `compare() → list[str]` — Compara o código (sem docstrings) de cada arquivo alterado com a versão no HEAD.
- `main(argv) → int` — Executa a comparação e imprime o resultado.

- `_strip_docstrings(tree) → ast.AST` — Remove docstrings de um corpo de classe ou função.
- `_head_source(path) → str | None` — Conteúdo da versão do arquivo no commit HEAD.
- `_changed_files() → list[str]` — Arquivos Python alterados na árvore de trabalho.
### `scripts/check_docs.py`

**Propósito:** Conferir que os links internos da documentação existem no repositório. **Quando/onde:** antes de publicar mudanças de documentação.

- `_sem_codigo(texto) → str` — Remove os trechos entre crases (código inline) antes de procurar links.

- `main(argv) → int` — Verifica os links da documentação.

- `_targets(paths) → list[Path]` — Arquivos Markdown a verificar.
- `_resolve(source, target) → Path | None` — Resolve o destino de um link a partir do arquivo que o contém.
- `_normalizar(texto) → str` — Forma comparável de um título ou de uma âncora.
- `_ancoras_validas(arquivo) → list[str]` — Âncoras internas de um documento que não correspondem a nenhum título.
### `scripts/padronizar_cabecalhos.py`

**Propósito:** Aplicar o cabeçalho padrão (campos `Arquivo`, `Nome`, `Propósito`, …) nos módulos Python, sem alterar o código. **Quando/onde:** ao padronizar uma pasta de módulos.

- `header_for(path) → str` — Monta o cabeçalho padrão de um módulo.
- `insert_header(path, header, narrative) → bool` — Insere (ou funde) o cabeçalho na primeira instrução do módulo.
- `main(argv) → int` — Aplica o cabeçalho nos arquivos informados.

- `_relative(path) → str` — Caminho do arquivo relativo à raiz do repositório.
- `_layer(relative) → tuple[str, str]` — Camada arquitetural e nota de observância a partir do caminho.
- `_purpose(relative, tree, lines) → str` — Propósito do módulo: narrativa existente, título do arquivo ou docstring atual.
- `_components(tree) → str` — Símbolos públicos de nível superior do módulo.
- `_dependencies(tree) → str` — Módulos importados pelo arquivo (internos primeiro).
- `_sem_comentario_de_caminho(lines, path) → list[str]` — Remove a linha `# caminho — propósito` (ela duplica o cabeçalho).
### `src/agent/automation/actions/README.md`

**Propósito:** índice da pasta de ações de automação — o que cada ação faz e como criar uma nova. **Quando/onde:** ao mexer no que a automação executa.

### `src/agent/automation/service/README.md`

**Propósito:** índice dos adaptadores de serviço nativo (launchd, systemd, Windows). **Quando/onde:** ao mexer no arranque do supervisor sem interface.

### `src/agent/automation/triggers/README.md`

**Propósito:** índice dos gatilhos (temporal e evento interno) e do papel da idempotência do disparo. **Quando/onde:** ao mexer no *quando* a automação dispara.

### `src/agent/skills/catalog/README.md`

**Propósito:** índice do catálogo de skills — o carregador que lê e valida o catálogo disponível. **Quando/onde:** ao mexer na origem das skills.

### `src/agent/api/README.md`

**Propósito:** Índice da pasta `api/` (main.py, observe_routes.py, deps.py).

### `src/agent/api/__init__.py`

**Propósito:** Marca o pacote `api` como parte do `agent`.

### `src/agent/api/deps.py`

**Propósito:** Dependências FastAPI — `db_session` (Session), `read_settings` (Settings), `get_engine` (Engine singleton).

- `db_session() -> Generator[Session, None, None]` — Dependência FastAPI que abre uma sessão SQLAlchemy e a fecha no fim da requisição; devolve a `Session` pronta para uso nas rotas.
- `get_engine()` — Símbolo do módulo — ver a descrição do arquivo.
- `get_session_factory() -> sessionmaker[Session]` — Dependency FastAPI — retorna session factory do SQLAlchemy (singleton via `get_engine()`).
- `read_settings() -> Settings` — Dependência FastAPI que devolve a configuração atual (`Settings`) lida do ambiente e do arquivo `.env`.

### `src/agent/api/main.py`

**Propósito:** Fachada da API HTTP: monta a aplicação FastAPI, inclui os roteadores por assunto, publica a SPA estática e sobe o servidor (`run()`). **Quando/onde:** importado por `agent.api.main:app` (uvicorn) e por `callidus-api`; as regras de cada rota vivem no serviço ou no orquestrador.

- `_web_dir(settings: Settings) -> Path | None` — Localiza a pasta do frontend: `settings.static_web_dir` se for diretório, senão `web/static` na raiz do repositório; devolve `None` quando nada existe.
- `lifespan(app: FastAPI)` — Gerenciador de contexto assíncrono do FastAPI: inicializa o engine, liga o worker em background se habilitado e garante o desligamento dele no `finally`.
- `run() -> None` — Entry point do console script `agente-api` — sobe o Uvicorn com a aplicação FastAPI no host/porta configurados.

- `_RevalidatedStatic` — Sem isso o navegador guarda a interface por heurística e mistura HTML antigo com módulos novos.
- `file_response(self, *args, **kwargs)` — Devolve o arquivo com o cabeçalho que proíbe o cache.
- `spa_index()` — Devolve o `index.html` da interface.

- `_mount_web(settings) → None` — Publica a interface estática e a página inicial da SPA.

- `_RevalidatedStatic.file_response(self, *args, **kwargs)` — Devolve o arquivo com o cabeçalho que proíbe o cache.
### `src/agent/api/system_routes.py`

**Propósito:** Rotas de sistema — saúde, provedores embutidos, ferramentas, MCP, preferências da interface e chat de debug. **Quando/onde:** a cada verificação de ambiente da interface ou de diagnóstico.

- `_RevalidatedStatic(StaticFiles)` — Subclasse de `StaticFiles` que força `Cache-Control: no-cache` em toda resposta de arquivo, evitando o navegador misturar HTML antigo com módulos novos.
- `_RevalidatedStatic.file_response(*args, **kwargs)` — Sobrescreve `StaticFiles.file_response` para acrescentar o cabeçalho `Cache-Control: no-cache` à resposta antes de devolvê-la.
- `_mount_web(settings: Settings) -> None` — Monta a SPA web estática no app FastAPI: publica `/assets` via `_RevalidatedStatic` e registra `GET /` servindo `index.html`; executado na importação do módulo.
- `debug_chat_ollama(body: dict, settings: Settings=Depends(read_settings)) -> dict` — chat direto Ollama (debug).
- `health() -> dict` — health check + versão.
- `list_events(project_id: uuid.UUID, session: Session=Depends(db_session)) -> list[EventRead]` — timeline de eventos.
- `list_tools() -> dict` — specs das ferramentas registradas.
- `tools_availability() -> dict` — Pré-requisitos presentes e ausentes de cada ferramenta registrada.
- `tools_families(settings: Settings=Depends(read_settings)) -> dict` — Famílias habilitadas, desligadas e o piso de risco automático.
- `system_diagnose() -> dict` — Diagnóstico do sistema, da sessão gráfica, das permissões e das dependências.
- `list_skills() -> dict` — Skills instaladas, com versão, estado e pasta.
- `llamacpp_models(settings: Settings=Depends(read_settings)) -> dict` — lista modelos llama.cpp.
- `mcp_call(body: dict, settings: Settings=Depends(read_settings)) -> dict` — chama ferramenta MCP.
- `mcp_discover(settings: Settings=Depends(read_settings)) -> dict` — descobre ferramentas nos servidores MCP.
- `mcp_servers(settings: Settings=Depends(read_settings)) -> dict` — servidores + ferramentas MCP.
- `ollama_models(settings: Settings=Depends(read_settings)) -> dict` — lista modelos Ollama.
- `project_live(project_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — estado atual para UI (thoughts, focus, action).
- `project_overview(project_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — resumo (tasks por status, run ativa).
- `run_execute(run_id: uuid.UUID, max_steps: int=50, session: Session=Depends(db_session), settings: Settings=Depends(read_settings)) -> dict` — múltiplos passos (`run_until_idle`).
- `run_step(run_id: uuid.UUID, session: Session=Depends(db_session), settings: Settings=Depends(read_settings)) -> dict` — um passo do orquestrador.
- `ui_defaults(settings: Settings=Depends(read_settings)) -> dict` — `GET /config/ui-defaults`: devolve os padrões de configuração da interface (provider, model_id, URLs de Ollama/llama.cpp, aprovação de tools e template genérico).
- `_mcp_path(settings: Settings) -> Path` — Resolve o arquivo de configuração MCP: usa `settings.mcp_config_path` ou `data_dir/mcp.json`; se não existir, cai no `data/mcp.example.json` da raiz do repositório.

- `list_providers(settings) → dict` — Provedores disponíveis: os do arquivo de configuração mais os embutidos. Nenhuma.
- `provider_by_name(name, settings)` — Constrói o provedor pedido ou responde com o erro correspondente.
- `provider_models(name, settings) → dict` — Lista os modelos de um provedor configurado.
- `provider_health(name, settings) → dict` — Diagnóstico de conectividade: sempre 200 com o resultado (ok true/false).
- `mcp_path(settings) → Path` — Resolve o caminho do arquivo de configuração do MCP.
### `src/agent/api/project_routes.py`

**Propósito:** Rotas de projeto — CRUD do projeto, computador remoto, filesystem, grafo de conhecimento, métricas, visão ao vivo, eventos e memória. **Quando/onde:** a cada ação sobre um projeto.

- `add_memory(project_id: uuid.UUID, body: MemoryCreate, session: Session=Depends(db_session)) -> MemoryRead` — `POST /projects/{project_id}/memory`: grava memória canônica ou contextual via `ProjectService.add_memory` e devolve `MemoryRead`; 404 se o projeto não existir.
- `create_project(body: ProjectCreate, session: Session=Depends(db_session)) -> ProjectRead` — `POST /projects`: cria o projeto via `ProjectService.create_project` e devolve o `ProjectRead` correspondente.
- `create_task(project_id: uuid.UUID, body: TaskCreate, session: Session=Depends(db_session)) -> TaskRead` — `POST /projects/{project_id}/tasks`: cria a tarefa detectando idioma, materializando anexos, tocando o título da conversa e extraindo memórias do objetivo; 404 projeto, 400 objetivo inválido.
- `fs_browse(path: str | None=None) -> dict` — `GET /fs/browse`: navega o sistema de arquivos local a partir de um caminho devolvendo diretórios e subpastas; 400 para caminho inválido.
- `fs_pick_folder() -> dict` — `POST /fs/pick-folder`: abre o seletor nativo de pastas do sistema operacional e devolve `{"path": ...}`; 400 quando não há seleção válida.
- `get_project(project_id: uuid.UUID, session: Session=Depends(db_session)) -> ProjectRead` — `GET /projects/{project_id}`: busca o projeto pelo id e devolve `ProjectRead`; 404 quando não encontrado.
- `kg_neighbors(project_id: uuid.UUID, ref: str, depth: int=1, session: Session=Depends(db_session)) -> dict` — `GET /projects/{project_id}/knowledge/neighbors`: busca no grafo de conhecimento os nós vizinhos de uma referência (profundidade limitada a 3) e devolve `{ref, nodes}`.
- `kg_reindex(project_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `POST /projects/{project_id}/knowledge/reindex`: reindexa o grafo do projeto a partir do `root_path` e devolve as estatísticas da indexação.
- `kg_search(project_id: uuid.UUID, q: str, limit: int=20, session: Session=Depends(db_session)) -> dict` — `GET /projects/{project_id}/knowledge/search`: pesquisa no grafo do projeto (limite máximo 100) e devolve `{query, hits}`.
- `list_memory(project_id: uuid.UUID, kind: MemoryKind | None=None, session: Session=Depends(db_session)) -> list[MemoryRead]` — `GET /projects/{project_id}/memory`: lista as memórias do projeto, opcionalmente filtradas por `MemoryKind`; 404 projeto inexistente.
- `list_projects(session: Session=Depends(db_session)) -> list[ProjectRead]` — `GET /projects`: lista todos os projetos persistidos e devolve a lista de `ProjectRead`.
- `list_runs(project_id: uuid.UUID, session: Session=Depends(db_session)) -> list[ExecutionRunRead]` — `GET /projects/{project_id}/runs`: lista as execuções do projeto em `list[ExecutionRunRead]`; 404 projeto inexistente.
- `list_tasks(project_id: uuid.UUID, session: Session=Depends(db_session)) -> list[TaskRead]` — `GET /projects/{project_id}/tasks`: lista as tarefas do projeto já apresentadas (título traduzido, usage, modelo); 404 projeto inexistente.
- `project_git_diff(project_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /projects/{project_id}/git-diff`: executa a ferramenta `git_diff` do registry com o `root_path` do projeto e devolve o diff do repositório.
- `project_metrics(project_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /projects/{project_id}/metrics`: devolve as métricas agregadas do projeto via `MetricsService.project_metrics`; 404 projeto inexistente.
- `start_run(project_id: uuid.UUID, body: ExecutionRunCreate, session: Session=Depends(db_session)) -> ExecutionRunRead` — `POST /projects/{project_id}/runs`: inicia uma execução para o projeto a partir de `ExecutionRunCreate` e devolve `ExecutionRunRead`; 404 projeto inexistente.
- `update_project(project_id: uuid.UUID, body: ProjectUpdate, session: Session=Depends(db_session)) -> ProjectRead` — `PATCH /projects/{project_id}`: atualiza nome e/ou `root_path` do projeto; 404 projeto inexistente, 400 valor inválido.

- `delete_project(project_id, session) → dict` — Remove o projeto e o que pertence a ele (conversas, tarefas, execuções, memória, grafo).
- `RemoteIn` — Configuração do computador remoto de um projeto.
- `get_project_remote(project_id, session) → dict` — Computador remoto configurado para o projeto (vazio quando o projeto é local).
- `set_project_remote(project_id, body, session) → dict` — Aponta o projeto para um computador remoto (Linux, macOS ou Windows) via SSH.
- `clear_project_remote(project_id, session) → dict` — Volta o projeto para a máquina local.
- `test_project_remote(project_id, session) → dict` — Testa a conexão com o computador remoto configurado.
- `FsMkdirIn` — Pedido de criação de uma pasta no sistema de arquivos.
- `fs_mkdir(body) → dict` — Cria uma pasta dentro do alcance permitido (para o seletor de pasta do projeto).
- `project_live(project_id, session) → dict` — Devolve a visão ao vivo do projeto: o que está rodando e o que vem a seguir.
- `project_overview(project_id, session) → dict` — Devolve o resumo do projeto: tarefas por estado, runs e raiz.
- `list_events(project_id, session) → list[EventRead]` — Lista os eventos registrados do projeto, do mais recente para o mais antigo.
### `src/agent/api/conversation_routes.py`

**Propósito:** Rotas de conversa — conversas soltas, mover, renomear, bifurcar, ativar ramo e as conversas de um projeto. **Quando/onde:** a cada ação sobre conversas.

- `activate_branch(conversation_id: uuid.UUID, branch_id: uuid.UUID, session: Session=Depends(db_session)) -> ConversationRead` — `POST /conversations/{conversation_id}/branches/{branch_id}/activate`: ativa a branch indicada e devolve a conversa atualizada; 404 se a conversa não existir.
- `conversation_tasks(conversation_id: uuid.UUID, branch_id: uuid.UUID | None=None, session: Session=Depends(db_session)) -> list[TaskRead]` — `GET /conversations/{conversation_id}/tasks`: lista as tarefas da conversa (branch ativa ou a `branch_id` informada) já apresentadas por `_present_task`; 404 conversa inexistente.
- `create_conversation(project_id: uuid.UUID, body: ConversationCreate, session: Session=Depends(db_session)) -> ConversationRead` — `POST /projects/{project_id}/conversations`: cria uma conversa dentro do projeto a partir do corpo e devolve `ConversationRead`; 404 projeto inexistente.
- `create_loose_conversation(body: ConversationCreate, session: Session=Depends(db_session)) -> ConversationRead` — `POST /conversations`: cria uma conversa sem projeto (inbox/"loose") e devolve `ConversationRead` com branches e raiz efetiva.
- `delete_conversation(conversation_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `DELETE /conversations/{conversation_id}`: remove a conversa e devolve `{"deleted": true}`; 404 se não existir.
- `fork_conversation(conversation_id: uuid.UUID, body: ConversationFork, session: Session=Depends(db_session)) -> dict` — `POST /conversations/{conversation_id}/fork`: cria a tarefa-filha a partir de `body.task_id` e `body.objective` e devolve a conversa com a nova task.
- `list_conversations(project_id: uuid.UUID, session: Session=Depends(db_session)) -> list[ConversationRead]` — `GET /projects/{project_id}/conversations`: lista as conversas do projeto (validando o projeto) com branches e raiz efetiva; 404 projeto inexistente.
- `list_loose_conversations(session: Session=Depends(db_session)) -> list[ConversationRead]` — `GET /conversations`: lista as conversas sem projeto (inbox) apresentadas por `_present_conversation`.
- `move_conversation(conversation_id: uuid.UUID, body: ConversationMove, session: Session=Depends(db_session)) -> ConversationRead` — `POST /conversations/{conversation_id}/move`: move a conversa para outro projeto (`body.project_id`) e devolve a conversa apresentada; 404 se não existir.
- `update_conversation(conversation_id: uuid.UUID, body: ConversationUpdate, session: Session=Depends(db_session)) -> ConversationRead` — `PATCH /conversations/{conversation_id}`: renomeia, define ou limpa o `root_path` da conversa conforme o corpo e devolve a conversa apresentada.

### `src/agent/api/task_routes.py`

**Propósito:** Rotas de tarefa — criação e leitura, status, dependências, contrato, snapshots de contexto, tentativas e evidências. **Quando/onde:** a cada ação sobre tarefas.

- `ResumeBody(BaseModel)` — Modelo Pydantic do corpo de `POST /tasks/{task_id}/resume-brief`; único campo `apply: bool = False` que decide se o brief é apenas informativo ou reaplica a execução.
- `add_dependency(task_id: uuid.UUID, body: TaskDependencyCreate, session: Session=Depends(db_session)) -> dict` — `POST /tasks/{task_id}/dependencies`: cria a dependência entre tarefas a partir do corpo e devolve `{id, task_id, depends_on}`; 404 tarefa inexistente, 400 dependência inválida.
- `get_context_snapshot(snapshot_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /context-snapshots/{snapshot_id}`: devolve o snapshot de contexto (tokens estimados, componentes, notas de estratégia, refs, timestamp) ou 404 se não existir.
- `get_task(task_id: uuid.UUID, session: Session=Depends(db_session)) -> TaskRead` — `GET /tasks/{task_id}`: devolve a tarefa apresentada (título traduzido, usage, modelo lembrado) em `TaskRead`; 404 se não existir.
- `get_task_contract(task_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /tasks/{task_id}/contract`: devolve o contrato da tarefa (inputs, outputs, invariantes, aceite) ou 404 quando o contrato não foi definido.
- `task_attempts(task_id: uuid.UUID, session: Session=Depends(db_session)) -> list[dict]` — `GET /tasks/{task_id}/attempts`: lista as tentativas de operação da tarefa (kind, provider, sucesso, erro, timestamp) da mais nova para a mais antiga.
- `task_context_snapshots(task_id: uuid.UUID, session: Session=Depends(db_session)) -> list[dict]` — `GET /tasks/{task_id}/context-snapshots`: devolve até 20 snapshots de contexto da tarefa (tokens, componentes, notas, refs) ordenados por data decrescente.
- `task_evidences(task_id: uuid.UUID, session: Session=Depends(db_session)) -> list[dict]` — `GET /tasks/{task_id}/evidences`: lista as evidências de verificação da tarefa (verifier, passed, summary).
- `task_resume_brief(task_id: uuid.UUID, body: ResumeBody, session: Session=Depends(db_session)) -> dict` — `POST /tasks/{task_id}/resume-brief`: sobe até a tarefa raiz e devolve o brief de retomada; com `body.apply` reativa a execução e devolve `reactivated_run_id`.
- `update_task_status(task_id: uuid.UUID, body: TaskStatusUpdate, session: Session=Depends(db_session)) -> TaskRead` — `PATCH /tasks/{task_id}/status`: aplica a mudança de status validando a máquina de estados; 404 tarefa inexistente, 409 transição inválida.
- `upsert_task_contract(task_id: uuid.UUID, body: dict, session: Session=Depends(db_session)) -> dict` — `PUT /tasks/{task_id}/contract`: grava (cria ou atualiza) o contrato com inputs/outputs/invariantes/aceite e devolve o impacto da mudança; 404 tarefa inexistente.

- `create_task(project_id, body, session) → TaskRead` — Cria uma tarefa no projeto, materializando anexos e memórias pedidas no objetivo.
- `list_tasks(project_id, session) → list[TaskRead]` — Lista as tarefas de um projeto.
### `src/agent/api/run_routes.py`

**Propósito:** Rotas de execução — iniciar, avançar, pausar, retomar, cancelar, modo autônomo e métricas do run. **Quando/onde:** a cada ação sobre uma execução.

- `cancel_run(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `POST /runs/{run_id}/cancel`: cancela a execução e devolve `{id, status}`; 404 se a run não existir.
- `disable_autonomous(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `POST /runs/{run_id}/autonomous/disable`: desliga o modo autônomo ajustando `config_json["autonomous"]` para `False`, faz commit e devolve `{id, autonomous}`.
- `enable_autonomous(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `POST /runs/{run_id}/autonomous/enable`: habilita o modo autônomo via `enable_autonomous_on_run`, faz commit e devolve `{id, autonomous}`.
- `pause_run(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `POST /runs/{run_id}/pause`: pausa a execução via `RunService.pause_run` e devolve `{id, status}`.
- `resume_run(run_id: uuid.UUID, retry_blocked: bool=False, session: Session=Depends(db_session)) -> dict` — `POST /runs/{run_id}/resume`: retoma a run pausada, opcionalmente repetindo tarefas bloqueadas (`retry_blocked`); 404 run inexistente, 409 quando não pode retomar.
- `run_metrics(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /runs/{run_id}/metrics`: devolve as métricas da execução (tokens, tempos) via `MetricsService.run_metrics` ou 404 se a run não existir.

- `start_run(project_id, body, session) → ExecutionRunRead` — Inicia uma execução no projeto.
- `list_runs(project_id, session) → list[ExecutionRunRead]` — Lista as execuções de um projeto.
- `run_step(run_id, session, settings) → dict` — Executa um único passo do orquestrador sobre a run.
- `run_execute(run_id, max_steps, session, settings) → dict` — Avança a run em vários passos até ela parar ou o orçamento acabar.
### `src/agent/api/presenters.py`

**Propósito:** Montagem dos payloads de leitura (tarefa e conversa) devolvidos pela API. **Quando/onde:** em toda resposta de leitura de tarefa ou conversa.

- `present_conversation(session: Session, item: ConversationModel) -> ConversationRead` — Serializa a conversa em `ConversationRead`, garantindo a branch ativa, anexando branches, `root_path` efetivo e `path_origin` (chosen/home), e ocultando `project_id` nas conversas da inbox.
- `present_task(session: Session, task) -> TaskRead` — Monta o `TaskRead` da tarefa, traduzindo o título para o idioma da tarefa e preenchendo `usage_tokens` e `metadata_json` com o modelo lembrado.
- `remembered_model(session: Session, task) -> dict` — Devolve os metadados da tarefa preservando `model_id`; se a tarefa raiz não tiver modelo, procura na run mais recente que a iniciou para recuperar o `model_id` usado.
- `usage_tokens(session: Session, task) -> int` — Estima os tokens consumidos pela tarefa: usa `metadata["usage"]["total"]` quando existe, senão o `estimated_tokens` do snapshot de contexto mais recente.

### `src/agent/api/live_view.py`

**Propósito:** Linha do tempo de pensamentos e texto legível das ações do orquestrador. **Quando/onde:** ao montar a visão ao vivo do projeto.

- `how_for_task(task) -> str` — Deriva dos metadados da tarefa (tool, verification, model_operation, mcp_tool) uma frase curta explicando como ela será executada; o fallback descreve a máquina de estados do orquestrador.
- `mark_repeated_thought(thoughts: list[dict], item: dict) -> None` — Calcula no item o contador `repeat` (1 ou 2+) comparando o texto com os pensamentos já coletados, para a interface mostrar que a frase se repetiu sem mudança.
- `thought_trace(session: Session, project_id: uuid.UUID, tasks: list) -> list[dict]` — Lê os eventos `agent.thought`/`orchestrator.action` do projeto, traduz as ações por `ACTION_COPY`, descarta ações internas e devolve os 16 pensamentos mais recentes com fase, texto e task associada.

### `src/agent/api/observe_routes.py`

**Propósito:** Expõe o histórico paginado de eventos, a foto do estado de uma run e a transmissão SSE em tempo real das execuções. **Quando/onde:** Router incluído em `main.py` (`app.include_router(observe_router)`), consumido pela interface web para acompanhar uma run ao vivo.

- `replay(since) → AsyncIterator[str]` — Relê o histórico persistido a partir de um `seq` e emite o que falta.

- `_Disconnectable(Protocol)` — Protocolo estrutural com `is_disconnected`, usado para tipar o objeto de requisição dentro do gerador SSE sem acoplar ao FastAPI.
- `_Disconnectable.is_disconnected() -> bool` — Método do protocolo: indica de forma assíncrona se o cliente (navegador) já desconectou da conexão SSE.
- `_page(factory: sessionmaker[Session], run_id: uuid.UUID, after: int) -> dict[str, Any]` — Lê do banco uma página de até 500 eventos da run com `seq` maior que `after`; executada em thread (`asyncio.to_thread`) pelo stream.
- `_run_or_404(session: Session, run_id: uuid.UUID) -> ExecutionRunModel` — Busca a run pelo id e levanta `HTTPException 404` ("run não encontrada") quando ela não existe.
- `_sse(data: dict[str, Any], *, event: str | None=None, seq: int | None=None) -> str` — Monta um frame SSE (linhas `event:`, `id:` e `data:` com JSON serializado) terminado em linha em branco.
- `_status(factory: sessionmaker[Session], run_id: uuid.UUID) -> str | None` — Consulta em thread o status atual da run no banco; devolve `None` quando a run não existe.
- `run_events(run_id: uuid.UUID, after: int=0, limit: int=200, types: str | None=None, task_id: uuid.UUID | None=None, tail: int | None=None, session: Session=Depends(db_session)) -> dict` — `GET /runs/{run_id}/events`: devolve o histórico persistido paginado (`after`+`limit`) ou os últimos `tail` eventos; `types` aceita tipos exatos, categorias ou prefixos separados por vírgula.
- `run_observe(run_id: uuid.UUID, session: Session=Depends(db_session)) -> dict` — `GET /runs/{run_id}/observe`: devolve a foto do estado da run lida do banco (tarefas, evidências, tentativas) somada ao que só existe em memória (saídas em andamento).
- `run_stream(run_id: uuid.UUID, request: Request, after: int | None=None, last_event_id: str | None=Header(default=None)) -> StreamingResponse` — `GET /runs/{run_id}/stream`: abre o `StreamingResponse` SSE da run, definindo o cursor inicial por `after` ou pelo header `Last-Event-ID` da reconexão do navegador.
- `sse_stream(run_id: uuid.UUID, request: _Disconnectable, after: int, *, factory: sessionmaker[Session], bus: EventBus, heartbeat: float=HEARTBEAT_SEC, max_age: float | None=None) -> AsyncIterator[str]` — Gerador assíncrono do SSE: assina o `EventBus` antes de ler o banco, reenvia o persistido após `after`, transmite eventos ao vivo sem repetir `seq`, responde a `RESYNC` relendo o banco e emite `end`/`rotate` conforme o fim da run ou `max_age`.

## `src/agent/context/`

**Propósito:** Montagem do prompt dentro do orçamento de tokens do modelo.

- Arquivo: [README.md](/src/agent/context/README.md)
- Arquivo: [__init__.py](/src/agent/context/__init__.py)
- Arquivo: [assembler.py](/src/agent/context/assembler.py)
- Arquivo: [budget.py](/src/agent/context/budget.py)
- Arquivo: [operation_builder.py](/src/agent/context/operation_builder.py)

- `replay(since) → AsyncIterator[str]` — Relê o histórico persistido a partir de um `seq` e emite o que falta.
### `src/agent/context/README.md`

**Propósito:** Índice da pasta `context/`.

### `src/agent/context/__init__.py`

**Propósito:** Re-exporta `budget`, `assembler`, `operation_builder`.

### `src/agent/context/assembler.py`

**Propósito:** `build_operation_context(...)` — monta componentes do prompt da operação (required + optional com prioridades).

- `build_operation_context(profile: ModelProfile, *, global_rules: str, project_rules: str, objective: str, technical: str, acceptance: str, tools_summary: str, output_format: str, previous_failures: str='', contract: str='', target_files: str='', global_objective: str='', dependency_results: str='', skills: str='', compact: bool=False) -> BudgetResult` — Monta os componentes do prompt da operação (obrigatórios e opcionais por prioridade) e devolve o `BudgetResult` com as mensagens, os tokens estimados e as notas de estratégia. Entradas: perfil do modelo e cada bloco de contexto; saída: prompt pronto dentro do orçamento.

### `src/agent/context/budget.py`

**Propósito:** Define o orçamento de tokens por chamada, a heurística de estimativa de tokens e o erro de estouro de contexto. **Quando/onde:** Usado na montagem do prompt (`assemble_messages`) e Whenever um componente obrigatório excede a janela do modelo.

- `BudgetResult` — resultado da montagem.
- `ContextBudgetError(ValueError)` — exceção quando obrigatórios > orçamento.
- `ContextBudgetError.__init__(budget: int, required_tokens: int, breakdown: list[dict]) -> None` — Constrói o `ValueError` que sinaliza que os componentes obrigatórios não cabem no orçamento; guarda `budget`, `required_tokens` e o `breakdown` (custo por componente) para diagnóstico, além do `snapshot_id` preenchido depois pelo orquestrador.
- `ContextComponent` — componente com prioridade.
- `assemble_messages(profile: ModelProfile, components: list[ContextComponent], *, safety_margin: int=256) -> BudgetResult` — adiciona required (sempre), depois optional por prioridade até estourar input_budget; `ContextBudgetError` se required não couber.
- `compact_text(text: str) -> str` — remove linhas duplicadas consecutivas + espaços extras (não corta conteúdo semântico).
- `estimate_tokens(text: str) -> int` — Estima o custo de um texto em tokens pela heurística conservadora de ~4 caracteres por token (texto PT/EN misto). Retorna 0 para texto vazio e no mínimo 1 para texto não vazio.

### `src/agent/context/operation_builder.py`

**Propósito:** Monta o contexto operacional de uma tarefa (regras, memória, contrato, arquivos-alvo, guias, skills e falhas anteriores) dentro do orçamento do modelo e grava o snapshot do contexto. **Quando/onde:** Chamado pelo orquestrador antes de cada operação de modelo, por meio de `build_for_task`.

- `OperationContextBuilder._requirements_block(self, task) → str` — Requisitos obrigatórios que esta etapa responde, com o critério de cada um e o recorte do contrato de qualidade quando a etapa o herdou.
- `OperationContextBuilder._inspection_budget(self) → int` — Quantas leituras o modelo pode fazer antes de responder (o mesmo limite do ciclo).
- `OperationContextBuilder._inspection_block(self, task) → str` — O que a tentativa anterior já leu: evita reler os mesmos arquivos do zero.

- `OperationContextBuilder` — Classe que monta, para uma tarefa, os blocos de contexto consumidos pelo modelo (objetivo global, regras, memória, contrato, arquivos, guias, skills, falhas), respeitando o orçamento de tokens e persistindo um `ContextSnapshotModel` do resultado.
- `OperationContextBuilder.__init__(session: Session, settings: Any=None) -> None` — Inicializa o construtor guardando a sessão SQLAlchemy, as configurações e o `KnowledgeGraphService`.
- `OperationContextBuilder._settings() -> Any` — Configuração do processo usada para expor famílias de ferramentas.
- `OperationContextBuilder._capability_summary(root_path: str, task: TaskModel) -> str` — Resumo compacto das famílias extras que entram no prompt desta etapa.
- `OperationContextBuilder._ancestor_attachments(task: TaskModel) -> list[dict]` — Percorre a cadeia de tarefas-pai (com proteção contra ciclos) e concatena os `attachments` declarados em `metadata_json`. Retorna a lista de referências de anexos (imagens/textos) da tarefa e de seus ancestrais.
- `OperationContextBuilder._attachment_snippet(root_path: str, task: TaskModel) -> str` — Monta o bloco textual dos anexos do pedido: lista até 8 anexos e, para os do tipo `text`, o preview de até 2000 caracteres lido via `resolve_under_root` (ignora anexos ilegíveis). Retorna string vazia quando não há anexos.
- `OperationContextBuilder._contract_block(task: TaskModel) -> tuple[str, list[str]]` — Lê o contrato da tarefa no `ContractService` e devolve o corpo formatado (entradas, saídas, invariantes e aceite, truncados a 600 caracteres cada) e a lista de arquivos referenciados no contrato.
- `OperationContextBuilder._dependency_results(task: TaskModel) -> str` — Busca as tarefas das quais esta depende e monta uma linha por dependência com título, status e o resumo do `consolidated_result_json`. Retorna as linhas unidas por quebra de linha (vazio se não houver dependências).
- `OperationContextBuilder._failures_block(task: TaskModel) -> str` — Devolve o resumo das falhas anteriores da etapa (`describe_failures`) e, se houver, anexa a seção "Orientação de recuperação" vinda de `metadata_json["recovery_guidance"]` — a orientação do ciclo diagnóstico → correção → re-verificação.
- `OperationContextBuilder._global_objective(task: TaskModel) -> str` — Sobe até a tarefa-raiz pela cadeia de `parent_id` e devolve o objetivo global (até 800 caracteres) quando ele difere do objetivo da tarefa atual. Retorna string vazia quando a tarefa já é a raiz ou compartilha o mesmo objetivo.
- `OperationContextBuilder._image_payloads(root_path: str, task: TaskModel, profile: ModelProfile) -> list[str]` — Converte anexos de imagem em base64 para envio multimodal, lendo os bytes sob a raiz do projeto. Devolve lista vazia se o perfil não suporta visão, se o arquivo estoura 4 MB ou se não há anexos de imagem (máximo de 2 imagens).
- `OperationContextBuilder._max_skills() -> int` — Lê `skills_max_per_operation` das settings e devolve o limite de Skills por operação (mínimo 1). Cai para 2 quando a configuração está ausente, para não impedir a execução.
- `OperationContextBuilder._memory_block(project_id: uuid.UUID, task: TaskModel) -> tuple[str, str]` — Escolhe as memórias relevantes ao objetivo e monta as linhas de contexto (`projeto`/`conversa` + tipo + título + fragmento). Retorna o bloco textual (ou "(sem memória registrada)") e uma nota de diagnóstico com o tamanho do índice e quantas memórias foram escolhidas.
- `OperationContextBuilder._memory_bodies(ids: list[uuid.UUID]) -> dict[uuid.UUID, str]` — Busca no banco os conteúdos completos das memórias indicadas. Retorna um dicionário `id → content` (vazio quando a lista de ids é vazia).
- `OperationContextBuilder._memory_index(project_id: uuid.UUID, task) -> list[dict]` — Monta o índice de memórias visíveis do projeto e da conversa, filtrando por `memory_visible` e derivando o outline de cada registro. Retorna até 24 dicionários com `id`, `title`, `summary`, `facts`, `topics`, `kind` e `scope`.
- `OperationContextBuilder._skills_block(root_path: str, task: TaskModel, profile: ModelProfile) -> tuple[str, list[SkillMatch]]` — Seleciona as Skills com `SkillSelector` (por estratégia profissional ou por palavras-chave do objetivo), renderiza suas instruções e limita o bloco a ~12% do orçamento de entrada (entre 400 e 2500 caracteres). Retorna o texto renderizado e a lista de `SkillMatch` aplicada.
- `OperationContextBuilder._target_files(root_path: str, task: TaskModel, extra: list[str]) -> tuple[str, list[str]]` — Seleciona os arquivos citados no pedido (título, objetivo, aceite, contrato e `path` da ferramenta) que existem sob a raiz e monta seus conteúdos, truncando em 8000 caracteres por arquivo e 12000 no total. Retorna o bloco de arquivos e a lista de caminhos incluídos.
- `OperationContextBuilder._technical_snippet(project_id: uuid.UUID, objective: str) -> str` — Busca no grafo de conhecimento os símbolos mencionados no objetivo (até 8 tokens, 3 hits cada) e devolve as referências encontradas. Retorna um aviso para usar `list_dir`/`search_grep` quando nada é encontrado.
- `OperationContextBuilder.build_for_task(*, project_id: uuid.UUID, root_path: str, task: TaskModel, profile: ModelProfile, run_id: uuid.UUID | None=None, compact: bool=False) -> tuple[BudgetResult, ContextSnapshotModel]` — Monta o prompt completo da operação (objetivo, contrato, regras, memórias, arquivos citados, skills selecionadas, dependências) respeitando o orçamento do modelo, grava o `ContextSnapshotModel` e devolve `(BudgetResult, ContextSnapshotModel)`.
- `_result_summary(result: dict | None, limit: int=400) -> str` — Resume o `consolidated_result_json` de uma tarefa, preferindo os campos `summary`, `stdout`, `content` ou `markdown` e, na ausência deles, serializando o resultado em JSON. Retorna "(sem resultado)" para entrada vazia e trunca no limite informado.

## `src/agent/domain/`

**Propósito:** Contratos centrais do domínio: enums, schemas, máquina de estados e falhas.

- Arquivo: [README.md](/src/agent/domain/README.md)
- Arquivo: [__init__.py](/src/agent/domain/__init__.py)
- Arquivo: [enums.py](/src/agent/domain/enums.py)
- Arquivo: [failures.py](/src/agent/domain/failures.py)
- Arquivo: [schemas.py](/src/agent/domain/schemas.py)
- Arquivo: [state_machine.py](/src/agent/domain/state_machine.py)

- `_requirements_block(self, task) → str` — Requisitos obrigatórios que esta etapa responde, com o critério de cada um e o recorte do contrato de qualidade quando a etapa o herdou.
- `_inspection_budget(self) → int` — Quantas leituras o modelo pode fazer antes de responder (o mesmo limite do ciclo).
- `_inspection_block(self, task) → str` — O que a tentativa anterior já leu: evita reler os mesmos arquivos do zero.

- `OperationContextBuilder._requirements_block(self, task) → str` — Requisitos obrigatórios que esta etapa responde, com o critério de cada um e o recorte do contrato de qualidade quando a etapa o herdou.
- `OperationContextBuilder._inspection_budget(self) → int` — Quantas leituras o modelo pode fazer antes de responder (o mesmo limite do ciclo).
- `OperationContextBuilder._inspection_block(self, task) → str` — O que a tentativa anterior já leu: evita reler os mesmos arquivos do zero.
### `src/agent/domain/README.md`

**Propósito:** Índice da pasta `domain/`.

### `src/agent/domain/__init__.py`

**Propósito:** Re-exporta enums, state_machine, schemas, failures.

### `src/agent/domain/enums.py`

**Propósito:** Enums de domínio (StrEnum):

- `AttemptKind(StrEnum)` — : MODEL, TOOL, VERIFICATION.
- `MemoryKind(StrEnum)` — : CANONICAL, EXECUTION, CONTEXTUAL, EVIDENCE, PROCEDURE.
- `RunStatus(StrEnum)` — : ACTIVE, PAUSED, COMPLETED, FAILED, CANCELLED.
- `TaskKind(StrEnum)` — : OBJECTIVE, SUBSYSTEM, OPERATION.
- `TaskStatus(StrEnum)` — : PENDING, PLANNING, READY, RUNNING, VERIFYING, RETRY_PENDING, BLOCKED, COMPLETED, FAILED, CANCELLED.

### `src/agent/domain/failures.py`

**Propósito:** Taxonomia de falhas do orquestrador, com categorias, causas, dicas de retentativa e detecção de resposta truncada. **Quando/onde:** Usado para classificar erros de ferramenta, provider, contexto e verificação e para montar o contexto de falhas da tentativa seguinte.

- `Failure` — `as_dict()` para serialização.
- `Failure.as_dict() -> dict[str, Any]` — Serializa a falha (categoria, causa, detalhe, assinatura) em dicionário para gravar nos metadados da tarefa e nos eventos.
- `Failure.from_dict(data: dict[str, Any] | None) -> Failure | None` — Reconstrói uma `Failure` a partir de um dicionário serializado (`category`, `cause`, `detail`). Retorna `None` quando o dicionário é vazio ou tem chaves/valores inválidos.
- `Failure.retry_same_strategy() -> bool` — Indica se vale repetir a mesma abordagem: só falha da categoria `RECOVERABLE` admite retry, demais exigem mudar de estratégia ou intervenção. Retorna `True` ou `False`.
- `FailureCategory(StrEnum)` — : CHANGE_STRATEGY, OPERATIONAL_LIMIT, CONFIGURATION, EXTERNAL_UNAVAILABLE, BLOCKED_DEPENDENCY.
- `FailureCause(StrEnum)` — : INVALID_PLAN, REPEATED_PROMPT, REPEATED_OUTPUT, STAGNATION, ATTEMPTS_EXHAUSTED, CONTEXT_BUDGET, MAX_TASKS, MAX_DEPTH, APPROVAL_REQUIRED, EXECUTABLE_MISSING, INVALID_CONFIG, PROVIDER_DOWN, NETWORK_ERROR, TOOL_UNAVAILABLE, DEPENDENCY_FAILED, DEPENDENCY_CANCELLED.
- `classify_context_error(message: str) -> Failure` — Classifica um `ContextBudgetError` em falha de categoria `CONFIGURATION` com causa `CONTEXT_BUDGET`; devolve `None` quando o erro não é de contexto.
- `classify_model_output(content: str, parse_error: str | None, missing: list[str] | None=None) -> Failure | None` — Classifica a saída inválida do modelo (JSON ilegível, prompt truncado, saída repetida) na categoria e causa correspondentes.
- `classify_provider_error(message: str, exc: BaseException | None = None) -> Failure` — Classifica erro de provedor separando o transitório do permanente: tempo esgotado, conexão recusada, limite de uso (429) e erro de servidor (5xx) admitem repetição; pedido recusado (4xx) exige reformular; credencial inválida (401/403) exige ação de fora. O tipo da exceção manda quando existe; o texto é o reserva.
- `_http_status(low: str) -> int | None` — Extrai o código HTTP de uma mensagem de erro do provedor. Entrada: mensagem em minúsculas; saída: o código encontrado ou `None`.
- `classify_tool_result(out: dict[str, Any]) -> Failure | None` — Classifica o retorno de uma ferramenta (sucesso, approval_required, executável ausente, timeout) em falha categorizada.
- `classify_verification(passed: bool | None, summary: str, output: str='') -> Failure | None` — Classifica a reprovação de uma verificação (falha de teste, artefato ausente, erro de sintaxe) quando o verificador reprova de fato.
- `describe_failures(history: list[dict[str, Any]], *, limit: int=3, detail_chars: int=400) -> str` — Monta o resumo textual das últimas falhas (limite padrão de 3) para o contexto da próxima tentativa, com causa, detalhe truncado e o "O que fazer diferente" derivado de `retry_hint`. Retorna string vazia quando o histórico não tem falhas válidas.
- `looks_truncated(content: str) -> bool` — Detecta se a resposta do modelo foi cortada pelo limite de saída: cerca de código com número ímpar de ``` ou JSON aberto sem o `}` correspondente. Retorna `False` para conteúdo vazio.
- `retry_hint(failure: Failure) -> str` — Devolve a instrução de correção para a próxima tentativa conforme a `cause` da falha (saída inválida, truncada, erro de tool, verificação, provider). Retorna string vazia quando não há dica mapeada para a causa.

### `src/agent/domain/schemas.py`

**Propósito:** Contratos Pydantic de entrada e saída da API, cobrindo projetos, conversas, tarefas, execuções e memórias. **Quando/onde:** Usado na validação de payloads e na serialização das respostas HTTP da API.

- `BranchRead(BaseModel)` — Schema de leitura de um ramo de conversa (`id`, `conversation_id`, `parent_id`, `fork_task_id`, `created_at`) devolvido pela API.
- `ConversationCreate(BaseModel)` — Payload de criação de conversa, com `title` e `locale` opcionais. Valida a entrada da API para abrir uma nova conversa.
- `ConversationFork(BaseModel)` — Payload de bifurcação de conversa a partir de uma tarefa, exigindo `task_id` e `objective` não vazio. Usado quando o usuário abre um novo ramo a partir de uma tarefa existente.
- `ConversationMove(BaseModel)` — Payload de movimentação de conversa para outro projeto, com `project_id` opcional. Usado para realocar uma conversa entre projetos.
- `ConversationRead(BaseModel)` — Modelo de leitura de uma conversa com id, projeto, workspace, título, locale, raiz, origem do caminho, branch ativo, lista de branches e timestamps. `from_attributes` permite serializar direto do modelo ORM.
- `ConversationUpdate(BaseModel)` — Payload de atualização parcial de conversa (`title`, `root_path` e `clear_root` para apagar a raiz). Usado no PATCH de conversa.
- `EventRead(BaseModel)` — , `MemoryCreate/Read`, `ResumeBody`.
- `ExecutionRunCreate(BaseModel)` — Payload de criação de uma execução, com a tarefa-raiz e um `config` livre opcional. Usado para disparar um novo run do orquestrador.
- `ExecutionRunRead(BaseModel)` — Modelo de leitura de uma execução com id, projeto, tarefa-raiz, status (`RunStatus`) e timestamps. `from_attributes` habilita a serialização a partir do ORM.
- `MemoryCreate(BaseModel)` — Payload de criação de memória, com `kind`, `title`, `content` e vínculos opcionais de tarefa, conversa, branch e `source_refs`. Usado pela API de memória.
- `MemoryRead(BaseModel)` — Modelo de leitura de memória com id, projeto, escopo de conversa/branch, tipo, título, conteúdo, resumo, outline, versão, referências de origem e data de criação. `from_attributes` habilita a serialização a partir do ORM.
- `ProjectCreate(BaseModel)` — Payload de criação de projeto, exigindo `name` entre 1 e 200 caracteres, com `root_path` e `description` opcionais. Usado na API de projetos.
- `ProjectRead(BaseModel)` — Modelo de leitura de projeto com id, nome, raiz, descrição, origem do caminho e timestamps. `from_attributes` habilita a serialização a partir do ORM.
- `ProjectUpdate(BaseModel)` — Payload de atualização parcial de projeto (`name` e/ou `root_path` opcionais). Usado no PATCH de projeto.
- `TaskCreate(BaseModel)` — Payload de criação de tarefa, com título (1–500) e objetivo obrigatórios, escopo, aceite, `kind`, vínculos de conversa/branch/pai e `metadata` livre. Usado pela API e pela decomposição do orquestrador.
- `TaskDependencyCreate(BaseModel)` — Payload de criação de dependência entre tarefas, exigindo `depends_on_task_id`. Usado para declarar de qual tarefa uma etapa depende.
- `TaskRead(BaseModel)` — Modelo de leitura de tarefa com identificação, vínculos, título, objetivo, escopo, aceite, status, `kind`, ordem, metadados, resultado consolidado, timestamps e tokens de uso. `from_attributes` habilita a serialização a partir do ORM.
- `TaskStatusUpdate(BaseModel)` — Payload de mudança de status de uma tarefa, com `status` e `reason` opcional. Usado para transições manuais via API.

- `AgentRead` — Agente lógico: identidade, papel, estado e o que ele sabe.
- `AgentAsk` — Consulta de um agente a outro.
- `AgentDiscard` — Descarte do estado recuperável de um agente.
- `AgentQueryRead` — Consulta e sua resposta (correlacionadas por identificador).
### `src/agent/domain/state_machine.py`

**Propósito:** Define as transições válidas entre status de tarefa e o erro emitido quando uma transição é proibida. **Quando/onde:** Usado pelo orquestrador sempre que o status de uma `Task` muda de estado.

- `InvalidTransitionError(ValueError)` — Exceção levantada quando uma transição de status de tarefa não é permitida pela `ALLOWED_TRANSITIONS`.
- `InvalidTransitionError.__init__(current: TaskStatus, target: TaskStatus) -> None` — Constrói o `ValueError` de transição inválida, com a mensagem "Transição inválida: atual → alvo" e os atributos `current` e `target` para tratamento posterior. Levantado por `validate_transition`.
- `can_transition(current: TaskStatus, target: TaskStatus) -> bool` — Símbolo do módulo — ver a descrição do arquivo.
- `transition(current: TaskStatus, target: TaskStatus) -> TaskStatus` — valida e retorna target.
- `validate_transition(current: TaskStatus, target: TaskStatus) -> None` — levanta `InvalidTransitionError` se inválida.

## `src/agent/guides/`

**Propósito:** Descoberta de capacidade do modelo e digest de guias do projeto.

- Arquivo: [README.md](/src/agent/guides/README.md)
- Arquivo: [discover.py](/src/agent/guides/discover.py)

### `src/agent/guides/README.md`

**Propósito:** Índice da pasta `guides/`.

### `src/agent/guides/discover.py`

**Propósito:** Descobre guias de agentes e regras existentes no repositório (AGENTS.md, CLAUDE.md, GEMINI.md, regras de editor, SKILL.md) e informa as capacidades de resposta de um modelo. **Quando/onde:** Usado ao montar o contexto da operação (`guide_digest`) e ao gerar instruções de formato de resposta no chat.

- `GuideHit` — Dataclass que representa um guia encontrado, com `kind` (agents, claude, cursor-rule, skill…), `path` relativo à raiz e `text` já recortado. É o item devolvido por `discover_guides`.
- `_clip(root: Path, path: Path, kind: str, limit: int=PER_FILE) -> GuideHit | None` — Lê um arquivo de guia garantindo que ele está sob a raiz e ignorando diretórios descartados (`SKIP`); remove front matter de `.mdc`/arquivos iniciados por `---` e trunca no limite. Retorna `GuideHit` ou `None` se ilegível, vazio ou fora da raiz.
- `_read(root: Path, rel: str, kind: str, limit: int=PER_FILE) -> GuideHit | None` — Atalho que resolve um caminho relativo à raiz e delega a leitura a `_clip`. Usado para os arquivos known da raiz (AGENTS.md, CLAUDE.md, etc.).
- `_scoped(root: Path, folder: str, suffixes: tuple[str, ...]) -> list[Path]` — Lista até 4 arquivos de uma pasta específica (`.cursor/rules`, `.github/instructions`) com os sufixos aceitos, em ordem alfabética. Retorna lista vazia se a pasta não existir.
- `_skill_meta(raw: str, fallback: str) -> tuple[str, str]` — Extrai `name` e `description` do front matter de um `SKILL.md`, usando o nome da pasta como fallback e "fluxo reutilizável" como descrição padrão. Retorna o par (nome, descrição truncada em 240 caracteres).
- `_skills(root: Path) -> list[GuideHit]` — Varre `skills/`, `.agents/skills/` e `.cursor/skills/` em busca de `SKILL.md` e devolve até 8 `GuideHit` do tipo "skill" com nome e descrição. Ignora arquivos em diretórios descartados.
- `_strip_front_matter(text: str) -> str` — Remove o bloco de front matter (`---` … `---`) do início de um texto Markdown. Devolve o texto original quando não há front matter ou quando o bloco não é fechado.
- `capability_line(model_id: str) -> str` — linha de capacidade (ex.: "suporta ferramentas, streaming, visão").
- `discover_guides(project_root: str | Path, objective: str='') -> list[GuideHit]` — Varre a raiz em ordem de precedência (AGENTS/CLAUDE/GEMINI/copilot/cursor/llms/docs, README como fallback, regras de editor, SKILL.md e AGENTS.md de pastas citadas no objetivo), respeitando o teto total de caracteres. Retorna a lista de `GuideHit` encontrados.
- `guide_digest(project_root: str | Path, objective: str='') -> str` — resumo concatenado para injeção no prompt.
- `reply_capabilities(model_id: str) -> dict[str, bool]` — Informa quais formatos de resposta o chat aceita (markdown, headings, listas, tabelas, código, mermaid, fontes) e se o modelo suporta visão, detectada por marcadores no id do modelo. Retorna o dicionário de capacidades.

## `src/agent/i18n/`

**Propósito:** Internacionalização (pt/en/es) do prompt e dos rótulos.

- Arquivo: [README.md](/src/agent/i18n/README.md)
- Arquivo: [__init__.py](/src/agent/i18n/__init__.py)
- Arquivo: [locale.py](/src/agent/i18n/locale.py)

### `src/agent/i18n/README.md`

**Propósito:** Índice da pasta `i18n/`.

### `src/agent/i18n/__init__.py`

**Propósito:** Re-exporta `locale`.

### `src/agent/i18n/locale.py`

**Propósito:** Detecta o idioma do pedido e traduz textos fixos do orquestrador e glosários técnicos entre português, inglês e espanhol. **Quando/onde:** Usado para exibir pensamentos, títulos e mensagens de status no idioma do usuário.

- `_apply_glossary(text: str, source: str, target: str) -> str` — Traduz um texto substituindo verbos do idioma de origem no início da string e, em seguida, os termos do glosário (do mais longo para o mais curto, com limites de palavra). Devolve o texto inalterado quando origem ou destino não são códigos suportados.
- `detect_language(text: str) -> str` — heurística por palavras-chave.
- `language_instruction(code: str) -> str` — instrução para o modelo.
- `translate(text: str, target: str, *, _depth: int=0) -> str` — tradução simples de labels conhecidos.

## `src/agent/knowledge/`

**Propósito:** Grafo de conhecimento do projeto (símbolos e imports).

- Arquivo: [README.md](/src/agent/knowledge/README.md)
- Arquivo: [graph_service.py](/src/agent/knowledge/graph_service.py)
- Arquivo: [indexer.py](/src/agent/knowledge/indexer.py)

### `src/agent/knowledge/README.md`

**Propósito:** Índice da pasta `knowledge/`.

### `src/agent/knowledge/graph_service.py`

**Propósito:** mantém o grafo de conhecimento do projeto (nós de arquivo/símbolo e arestas) persistido nas tabelas `kg_nodes` e `kg_edges`. **Quando/onde:** usado pelo serviço de knowledge graph para reindexar a árvore do projeto, consultar vizinhos e símbolos, e tocar arquivos alterados.

- `KnowledgeGraphService` — Serviço que mantém o grafo de conhecimento do projeto no SQLite: upsert de nós e arestas, busca textual e consulta de vizinhança.
- `KnowledgeGraphService.__init__(session: Session) -> None` — guarda a sessão SQLAlchemy usada para ler e escrever nós e arestas. Entrada: sessão do banco; saída: `None` (efeito colateral: instância pronta para as operações do grafo).
- `KnowledgeGraphService._node_dict(n: KgNodeModel) -> dict` — converte uma linha `KgNodeModel` no dicionário serializável `{id, kind, ref, label, meta}` devolvido pela API. Entrada: nó do grafo; saída: dicionário simples. Quando o serviço lista vizinhos ou resultados de busca.
- `KnowledgeGraphService._upsert_node(project_id: uuid.UUID, spec: dict) -> KgNodeModel` — procura o nó por (projeto, `kind`, `ref`) e o cria com `flush` quando ainda não existe, guardando o resto do spec em `meta_json`. Entrada: id do projeto e spec (`kind`, `ref`, `label` e extras); saída: o modelo `KgNodeModel` persistido. Quando `touch_file` registra arquivo e símbolos.
- `KnowledgeGraphService.neighbors(project_id: uuid.UUID, ref: str, depth: int=1) -> list[dict]` — Devolve os nós vizinhos de uma referência, expandindo até `depth` saltos, para contextualizar o símbolo alterado.
- `KnowledgeGraphService.reindex(project_id: uuid.UUID, root_path: str) -> dict` — Varre todos os arquivos `.py` do projeto (até o limite configurado) e reconstrói nós e arestas de import; devolve o resumo do que foi indexado.
- `KnowledgeGraphService.search(project_id: uuid.UUID, query: str, limit: int=20) -> list[dict]` — Busca textual no grafo por `ref`/`label` (ILIKE) e devolve até `limit` nós com seus metadados.
- `KnowledgeGraphService.touch_file(project_id: uuid.UUID, root_path: str, rel_path: str) -> None` — Reindexa um único arquivo (incremental) e atualiza as arestas de import dele.

### `src/agent/knowledge/indexer.py`

**Propósito:** indexa arquivos e símbolos do projeto por AST, produzindo os nós e arestas do grafo de conhecimento. **Quando/onde:** chamado pelo `KnowledgeGraphService` na indexação inicial do projeto e ao tocar arquivos Python.

- `_py_import_edges(path: Path, root: Path) -> list[dict]` — lê o AST do arquivo Python e devolve uma aresta `imports` para cada `import`/`from ... import`, com o destino no formato `modulo/caminho.py`. Entrada: caminho do arquivo e raiz do projeto; saída: lista de dicionários `src_ref`/`dst_ref`/`rel` (vazia se o arquivo não compilar).
- `_py_symbols(path: Path, root: Path) -> list[dict]` — extrai do AST as funções e classes do arquivo, devolvendo specs `{kind, ref ("arquivo::Nome"), label, line}`; sem símbolos, devolve um único nó do tipo `file`. Entrada: caminho e raiz; saída: lista de specs de nós. Quando o indexador monta os nós de código.
- `grep_symbols_in_objective(objective: str) -> list[str]` — extrai do objetivo textual os identificadores de 3+ caracteres (letra inicial, resto alfanumérico/underscore) para casar com símbolos do projeto. Entrada: objetivo; saída: lista de strings candidatas. Quando se quer ligar o objetivo a símbolos indexados.
- `scan_project(root_path: str, *, max_files: int=500) -> tuple[list[dict], list[dict]]` — varre a árvore do projeto e monta o grafo inicial: nós de projeto/arquivo/símbolo/módulo/documento e arestas `contains`, `defines`, `imports`, `documents` e `tests`, parando em `max_files`. Entrada: raiz do projeto e limite de arquivos; saída: tupla `(nodes, edges)`. Quando o `KnowledgeGraphService.reindex` indexa tudo.

## `src/agent/mcp/`

**Propósito:** Integração com servidores MCP via stdio (JSON-RPC 2.0).

- Arquivo: [README.md](/src/agent/mcp/README.md)
- Arquivo: [config_models.py](/src/agent/mcp/config_models.py)
- Arquivo: [manager.py](/src/agent/mcp/manager.py)
- Arquivo: [stdio_transport.py](/src/agent/mcp/stdio_transport.py)

### `src/agent/mcp/README.md`

**Propósito:** Índice da pasta `mcp/`.

### `src/agent/mcp/config_models.py`

**Propósito:** `McpConfig`, `McpServerConfig` (Pydantic para `mcp.json`).

- `McpServerConfig` — Configuração Pydantic de um servidor MCP no `mcp.json` (comando, argumentos, variáveis de ambiente e timeout).

### `src/agent/mcp/manager.py`

**Propósito:** gerencia a configuração MCP: carrega servidores e ferramentas do arquivo JSON, descobre as ferramentas expostas e despacha as chamadas. **Quando/onde:** usado pelo orquestrador quando o modelo pede uma ferramenta `mcp:<servidor>:<ferramenta>` ou uma ferramenta MCP registrada.

- `McpManager` — Gerenciador dos servidores MCP stdio configurados: descobre as ferramentas de cada servidor e as chama via JSON-RPC 2.0.
- `McpManager.__init__(config_path: Path) -> None` — inicializa o gerenciador e já carrega a configuração do arquivo MCP. Entrada: caminho do JSON de configuração; saída: `None` (servidores e ferramentas ficam em memória).
- `McpManager._parse_tool_id(tool_id: str) -> tuple[str, str] | None` — separa um id no formato `mcp:<server_id>:<tool_name>` em `(server_id, tool_name)`, devolvendo `None` quando o id não segue esse padrão. Entrada: id da ferramenta; saída: tupla ou `None`. Quando `call_tool` decide entre invocação direta e registro.
- `McpManager.call_tool(tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]` — Chama uma ferramenta MCP pelo id, serializando os argumentos; devolve o resultado ou o erro do servidor.
- `McpManager.discover() -> dict[str, Any]` — Percorre todos os servidores, coleta as ferramentas de cada um e devolve o inventário consolidado (inclui erros de conexão).
- `McpManager.list_servers() -> list[McpServerConfig]` — Devolve a lista de servidores MCP configurados, com nome, comando e status.
- `McpManager.list_tools() -> list[dict[str, Any]]` — Conecta aos servidores e devolve as ferramentas MCP disponíveis (id, servidor e schema de argumentos).
- `McpManager.reload() -> None` — relê o JSON de configuração, recriando a lista de servidores e o mapa de ferramentas registradas e resetando `auto_discover`. Entrada: nenhuma (usa `self._config_path`); saída: `None`. Quando a configuração muda em disco.

### `src/agent/mcp/stdio_transport.py`

**Propósito:** fala com servidores MCP por stdio usando o SDK oficial, subindo o processo, listando ferramentas e invocando-as. **Quando/onde:** usado pelo `McpManager` na descoberta e na execução de ferramentas MCP.

- `_parameters(server: McpServerConfig) -> StdioServerParameters` — monta os parâmetros de processo stdio do SDK MCP a partir do comando e do `env` do servidor. Entrada: config do servidor; saída: `StdioServerParameters` (lança `ValueError` se o comando estiver vazio).
- `invoke_tool(server: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]` — sobe o processo stdio, inicializa a sessão MCP e chama a ferramenta, devolvendo `{success, is_error, content, structured}`. Entrada: servidor, nome da ferramenta e argumentos; saída: dicionário com o texto concatenado dos blocos e o conteúdo estruturado.
- `list_server_tools(server: McpServerConfig) -> list[dict[str, Any]]` — lista as ferramentas do servidor MCP e as devolve normalizadas, com id `mcp:<servidor>:<ferramenta>`, descrição e `input_schema`. Entrada: config do servidor; saída: lista de dicionários de ferramenta. Quando o `McpManager.discover` descobre ferramentas.

## `src/agent/memory/`

**Propósito:** Extração e gravação de memória (projeto e conversa).

- Arquivo: [README.md](/src/agent/memory/README.md)
- Arquivo: [__init__.py](/src/agent/memory/__init__.py)
- Arquivo: [store.py](/src/agent/memory/store.py)

### `src/agent/memory/README.md`

**Propósito:** Índice da pasta `memory/`.

### `src/agent/memory/__init__.py`

**Propósito:** Re-exporta `store`.

### `src/agent/memory/store.py`

**Propósito:** Resumir memórias na criação e recortá-las na leitura, entregando só os trechos relevantes ao objetivo dentro de um orçamento de caracteres. **Quando/onde:** Usado na gravação de memórias e na montagem do bloco de memória do contexto da operação.

- `_tokens(text: str) -> set[str]` — Extrai o conjunto de tokens normalizados (minúsculos, 4+ caracteres) de um texto. É a base da comparação por sobreposição usada na escolha de memórias.
- `choose_memory_index(rows: list[dict], objective: str, *, limit: int=4) -> list[dict]` — Pontua cada registro de memória pela sobreposição de tokens entre o objetivo e título/resumo/tópicos/fatos, preservando a ordem original como desempate e sempre garantindo ao menos uma memória de escopo "projeto" quando existir. Retorna no máximo `limit` dicionários.
- `decompose_for_use(text: str, objective: str, *, budget: int=480) -> list[str]` — Quebra o texto em parágrafos/frases, ordena por sobreposição com o objetivo e devolve apenas os trechos relevantes (ou o resumo, se nada casar), cortados no orçamento. Retorna a lista de fragmentos.
- `extract_memory_request(text: str) -> tuple[str, str] | None` — regex para "lembre-se", "grave na memória", "anote que", "remember".
- `fragments_for_prompt(summary: str, content: str, objective: str, *, budget: int=480) -> str` — Combina o resumo com os fragmentos relevantes do conteúdo completo, evitando duplicar o resumo, e trunca o resultado no orçamento. Retorna o texto final para o prompt.
- `structure_memory(text: str) -> dict` — Gera o índice estruturado de uma memória: resumo, até 8 fatos (parágrafos truncados) e até 6 tópicos. Retorna o dicionário `{"summary", "facts", "topics"}` sem o texto completo.
- `summarize_text(text: str, limit: int=320) -> str` — Produz um resumo curto do texto, preferindo frases completas e preservando o texto íntegro quando ele já cabe no limite. O conteúdo completo continua guardado em outro campo.

## `src/agent/observability/`

**Propósito:** Barramento de eventos, emissor, sanitização e snapshots da execução.

- Arquivo: [README.md](/src/agent/observability/README.md)
- Arquivo: [__init__.py](/src/agent/observability/__init__.py)
- Arquivo: [batching.py](/src/agent/observability/batching.py)
- Arquivo: [bus.py](/src/agent/observability/bus.py)
- Arquivo: [contracts.py](/src/agent/observability/contracts.py)
- Arquivo: [emitter.py](/src/agent/observability/emitter.py)
- Arquivo: [sanitize.py](/src/agent/observability/sanitize.py)
- Arquivo: [snapshot.py](/src/agent/observability/snapshot.py)

### `src/agent/observability/README.md`

**Propósito:** Índice da pasta `observability/`.

### `src/agent/observability/__init__.py`

**Propósito:** Re-exporta `bus`, `emitter`, `batching`, `snapshot`, `sanitize`, `contracts`.

### `src/agent/observability/batching.py`

**Propósito:** Agrupa fragmentos de texto antes de publicar, cortando o lote por tamanho ou por intervalo de tempo. **Quando/onde:** Usado pelos provedores de modelo e pelo executor de comandos ao emitir eventos de saída parcial (`agent.output.delta`, `tool.output`, `command.output`).

- `DeltaBatcher` — Símbolo do módulo — ver a descrição do arquivo.
- `DeltaBatcher.__init__(publish: Callable[[str], None], *, interval_ms: int | None=None, max_chars: int | None=None) -> None` — Constrói o acumulador com a callback `publish` que recebe cada lote de texto; os limites vêm das settings (`stream_delta_interval_ms`, `stream_delta_max_chars`) quando `interval_ms`/`max_chars` são `None`. Deixa buffer vazio, temporizador desligado e contadores `batches`/`chars` em zero.
- `DeltaBatcher.add(text: str) -> None` — Acumula um fragmento de saída e devolve `True` quando o lote deve ser enviado (intervalo ou tamanho máximo atingido).
- `DeltaBatcher.flush() -> None` — Envia o buffer acumulado ao callback `on_flush` e zera o buffer; não faz nada quando o buffer está vazio.
- `_defaults() -> tuple[int, int]` — Lê com cache (`lru_cache`) o par `(interval_ms, max_chars)` das settings; usado no `__init__` para não repetir a leitura de configuração.

### `src/agent/observability/bus.py`

**Propósito:** Barramento em memória por run: sequência monotônica, anel de eventos recentes, assinantes com fila e o texto parcial das saídas/operações em andamento. **Quando/onde:** Usado pelo SSE/API para entregar eventos em tempo real; os fatos duráveis permanecem em `event_logs`.

- `EventBus` — Símbolo do módulo — ver a descrição do arquivo.
- `EventBus.__init__(*, ring_size: int=3000, queue_size: int=1000, max_runs: int=64) -> None` — Cria o barramento com anel de `ring_size` envelopes por run, filas de `queue_size` por assinante e no máximo `max_runs` runs mantidas em memória (LRU), serializando o acesso com um `RLock`.
- `EventBus._deliver(sub: Subscription, env: dict[str, Any]) -> None` — Entrega o envelope na fila do assinante; se a fila estiver cheia (assinate lento), descarta o conteúdo pendente, contabiliza a perda em `sub.dropped` e enfileira um evento `stream.resync` para o cliente recuperar do banco.
- `EventBus._ensure(run_id: str, initial: Callable[[], int]) -> _RunState` — Devolve o estado volátil da run, criando-o (com `seq` inicial vindo de `initial()`) se ainda não existir; ao passar de `max_runs`, descarta a run mais antiga que não tenha assinantes.
- `EventBus._state(run_id: str) -> _RunState | None` — Busca o estado da run e o move para o fim do `OrderedDict` (reforçando o LRU); devolve `None` quando a run é desconhecida neste processo.
- `EventBus._track(st: _RunState, env: dict[str, Any]) -> None` — Atualiza o rastreio interno da run:Registry de saídas do modelo (`outputs`) e de operações/ferramentas em andamento (`operations`).
- `EventBus.active_steps(run_id: str) -> int` — Quantos passos do orquestrador estão rodando agora para a run; vale zero após um reinício, pois o contador é só em memória.
- `EventBus.allocate_seq(run_id: str, initial: Callable[[], int]) -> int` — Reserva o próximo número de sequência monotônico da run; usa o valor inicial quando a run ainda não tem estado no barramento.
- `EventBus.last_seq(run_id: str) -> int | None` — Último `seq` publicado no processo para a run, ou `None` se a run não existe aqui (nesse caso o valor persistido deve ser consultado no banco).
- `EventBus.live(run_id: str) -> dict[str, Any]` — Devolve o estado vivo da run: saídas do modelo em streaming, operações abertas, último `seq` e contadores de publicação.
- `EventBus.publish(env: dict[str, Any]) -> None` — Publica um envelope no barramento: guarda no anel da run, notifica os assinantes e atualiza o rastreio de saídas e operações em andamento.
- `EventBus.recent(run_id: str, after_seq: int=0) -> list[dict[str, Any]]` — Devolve os eventos do anel da run com `seq` maior que `after_seq` — base do replay e da reconexão do SSE.
- `EventBus.reset() -> None` — Limpa estados de run e contadores de passo e fecha todas as assinaturas, esvaziando o registro de assinantes.
- `EventBus.step_finished(run_id: str) -> None` — Decrementa o contador de passos ativos da run, removendo a entrada quando o valor chega a zero.
- `EventBus.step_started(run_id: str) -> None` — Incrementa o contador de passos ativos da run, sinalizando que o orquestrador está executando.
- `EventBus.subscribe(run_id: str, loop: asyncio.AbstractEventLoop | None=None) -> Subscription` — Cria uma assinatura da run com fila assíncrona; devolve o handle `Subscription` usado para receber os eventos e para cancelar.
- `EventBus.subscriber_count(run_id: str | None=None) -> int` — Quantidade de assinantes de uma run específica ou, sem `run_id`, o total de assinantes de todas as runs.
- `EventBus.unsubscribe(sub: Subscription) -> None` — Fecha a assinatura e remove a fila do assinante do barramento.
- `Subscription` — Dataclass que representa um assinante: `run_id`, o event loop asyncio onde a entrega é agendada, a fila de envelopes, o flag `closed` e o contador `dropped` de eventos perdidos por fila cheia.
- `_RunState` — Dataclass com o estado volátil de uma run: `seq` atual, anel `deque` de envelopes, dicionários de saídas e operações em andamento, e contadores `published`/`ephemeral`.
- `_append(current: str, text: str, keep: int, *, tail: bool) -> str` — Concatena `text` a `current` respeitando o limite `keep` de caracteres; com `tail=True` preserva o trecho final (saída de comandos/testes) e com `tail=False` o inicial (texto do modelo).
- `get_bus() -> EventBus` — singleton (config via `Settings.stream_ring_size`, `stream_subscriber_queue`).

### `src/agent/observability/contracts.py`

**Propósito:** Contrato tipado dos eventos de execução: catálogo de tipos com campos obrigatórios, validação de payload e normalização de linhas do banco em envelopes. **Quando/onde:** Usado pelo emissor antes de persistir/publicar eventos e pela API ao reidr o histórico persistido.

- `EventEnvelope(BaseModel)` — Envelope Pydantic de um evento (tipo, run, `seq`, dados, timestamp e task opcional) — o formato único que circula pelo barramento e pela API.
- `EventSpec` — Dataclass imutável com a especificação de um tipo de evento: `type`, `category` (prefixo antes do ponto), `persist` (se o fato vai para `event_logs`), a tupla `required` de campos obrigatórios e `description`.
- `InvalidEventPayload(ValueError)` — Exceção levantada quando o payload do evento não tem os campos obrigatórios ou não é serializável em JSON.
- `UnknownEventType(ValueError)` — Exceção levantada quando o tipo de evento não existe no catálogo `EVENT_SPECS`.
- `_s(value: Any) -> str | None` — Converte um valor para `str` preservando `None`; usado para normalizar os UUIDs do banco em texto.
- `_spec(type_: str, required: tuple[str, ...]=(), *, persist: bool=True, description: str='') -> EventSpec` — Fábrica interna que monta um `EventSpec` derivando a categoria do prefixo de `type_`; usada para popular o catálogo `EVENT_SPECS`.
- `as_utc(value: datetime | None) -> datetime | None` — Normaliza datas: devolve `None` ou datetimes com fuso intactos e marca como UTC as datas "naive" devolvidas pelo SQLite.
- `envelope_from_row(row: Any) -> dict[str, Any]` — Converte uma linha de `event_logs` no dicionário de envelope (id, run/projeto/tarefa, type, seq, ts, data, versão de schema) entregue pela API e pelo SSE.
- `spec_for(event_type: str) -> EventSpec` — Devolve a especificação do tipo de evento; levanta `UnknownEventType` se o tipo não estiver no catálogo.
- `validate_payload(event_type: str, data: dict[str, Any] | None) -> dict[str, Any]` — Valida o payload contra a spec (campos obrigatórios e serializabilidade em JSON) e devolve uma cópia do dicionário; levanta `InvalidEventPayload` em caso de falha.

### `src/agent/observability/emitter.py`

**Propósito:** Contexto de observação da execução: liga eventos à run/tarefa, grava os fatos persistidos e publica os envelopes no barramento somente depois do commit. **Quando/onde:** Usado pelo orquestrador e pelas ferramentas dentro de um bloco `observe()`.

- `Observation` — Dataclass com o contexto de emissão: `session` SQLAlchemy, `run_id`, `project_id`, `task_id` e o `agent` responsável (padrão `"orchestrator"`).
- `_after_commit(session: Session) -> None` — Listener do SQLAlchemy que, após o commit, publica no barramento os envelopes acumulados em `session.info`; eventos persistidos só ficam visíveis depois de gravados.
- `_after_flush(session: Session, _ctx: Any) -> None` — Listener que, após o flush, converte as linhas pendentes de `event_logs` em envelopes e os guarda em `session.info` aguardando o commit.
- `_after_soft_rollback(session: Session, previous_transaction: Any) -> None` — Descarta linhas e envelopes pendentes em caso de rollback; em sub-transações (rollback aninhado) não faz nada, preservando o estado externo.
- `_before_flush(session: Session, _ctx: Any, _instances: Any) -> None` — Prepara as novas linhas de `event_logs` antes do flush: completa `run_id`/`project_id`/`agent`/`parent_task_id`, gera `id` e `created_at`, sanitiza o payload e aloca o `seq` no barramento.
- `_limit_for(event_type: str) -> int` — Limite de caracteres do payload conforme o tipo: `output_limit` para `agent.output.completed` e para tipos fora do catálogo, `text_limit` nos demais.
- `_limits() -> tuple[int, int]` — Lê com cache o par `(event_text_limit, event_output_limit)` das settings.
- `_max_seq(session: Session, run_id: uuid.UUID) -> int` — Maior `seq` já gravado no banco para a run, usado como base da sequência quando a run entra no processo.
- `_on_init(target: EventLogModel, _args: Any, _kwargs: Any) -> None` — Listener do evento `init` do modelo: marca cada linha nova com um contador de ordem, preservando a ordem de criação no flush.
- `_parent_of(session: Session, task_id: uuid.UUID | None) -> uuid.UUID | None` — Busca a tarefa e devolve o `parent_id`, ou `None` quando não há `task_id` ou a tarefa não existe.
- `current() -> Observation | None` — Devolve a observação ativa no contexto (ContextVar) ou `None` fora de um bloco `observe`.
- `emit(event_type: str, data: dict[str, Any] | None=None, *, task_id: Any=_UNSET, agent: str | None=None, commit: bool=False) -> EventLogModel | dict[str, Any] | None` — Emite um evento tipado: monta o envelope (run_id do contexto, `seq` do barramento, timestamp), sanitiza o payload, publica no barramento e — quando `commit=True` — grava o `EventLogModel` no SQLite. Devolve o envelope ou `None` fora de uma run.
- `install() -> None` — Registra uma única vez os listeners do SQLAlchemy (`init`, `before_flush`, `after_flush`, `after_commit`, `after_soft_rollback`); é idempotente e roda na importação do módulo.
- `observe(session: Session, *, run_id: uuid.UUID, project_id: uuid.UUID | None=None, task_id: uuid.UUID | None=None, agent: str='orchestrator') -> Iterator[Observation]` — Gerenciador de contexto que define a observação corrente (run, projeto, tarefa, agente) para que tudo emitido dentro do bloco saia associado a ela; restaura o contexto anterior ao sair.
- `scoped(*, task_id: Any=_UNSET, agent: str | None=None) -> Iterator[Observation | None]` — Gerenciador de contexto que troca temporariamente a tarefa e/ou o agente do contexto atual (sobre uma cópia, para não vazar); sem contexto ativo, não faz nada e devolve `None`.
- `set_task(task_id: uuid.UUID | None) -> None` — Troca a tarefa da observação corrente, dentro do bloco que a criou, de modo que os eventos seguintes fiquem vinculados a ela.

### `src/agent/observability/sanitize.py`

**Propósito:** Remove segredos dos textos e dos payloads e limita o tamanho do conteúdo que vai para os eventos. **Quando/onde:** Usado pelo emissor antes de persistir ou publicar qualquer payload.

- `is_sensitive_path(path: str | None) -> bool` — detecta `.env`, `secrets`, `keys`, `passwords`, `tokens`, `credentials`, `.pem`, `.key`, `.crt`.
- `redact_text(text: str) -> str` — Aplica os padrões de segredo (chaves privadas, tokens, senhas, chaves de API, credenciais em URL) e substitui os trechos encontrados por `[redigido]`.
- `sanitize(value: Any, *, limit: int=20000, _depth: int=0) -> Any` — Copia a estrutura recebida redigindo segredos e truncando textos, sem alterar tipos JSON básicos; descarta dicionários de `env`/`headers` e substitui valores de chaves sensíveis por `[redigido]`.
- `truncate(text: str, limit: int) -> str` — Limita o texto a `limit` caracteres preservando início e fim e inserindo um marcador com a quantidade de caracteres omitidos; devolve o texto intacto quando ele já couber.

### `src/agent/observability/snapshot.py`

**Propósito:** Monta a foto do estado real de uma run (tarefas, evidências, eventos) combinando o banco com o que só existe em memória no processo. **Quando/onde:** Usado pela API para renderizar o painel de acompanhamento e recuperar o histórico paginado de eventos.

- `_iso(value: datetime | None) -> str | None` — Serializa um datetime em ISO 8601 depois de normalizar o fuso para UTC; devolve `None` quando não há data.
- `_type_filter(types: list[str])` — Monta o filtro SQL de `event_type` a partir dos tipos pedidos: prefixo terminado em ponto casa por `startswith`, tipo completo casa por igualdade; devolve `None` quando a lista é vazia.
- `events_page(session: Session, run_id: uuid.UUID, *, after: int=0, limit: int=200, types: list[str] | None=None, task_id: uuid.UUID | None=None, tail: int | None=None) -> dict[str, Any]` — Devolve uma página de eventos persistidos em ordem de `seq` (paginação para frente a partir de `after` ou os `tail` últimos), com `next_after`, `has_more` e `last_seq`; linhas antigas sem `seq` ficam de fora.
- `last_seq(session: Session, run_id: uuid.UUID) -> int` — Maior `seq` gravado no banco para a run, ou zero se ainda não houver eventos.
- `open_operations(session: Session, run_id: uuid.UUID) -> list[dict[str, Any]]` — Lista chamadas ao modelo, ferramentas, comandos e testes que começaram (`*.started`) e não têm evento de conclusão gravado.
- `run_snapshot(session: Session, run_id: uuid.UUID, *, bus: EventBus | None=None, recent: int=300) -> dict[str, Any]` — Monta o retrato completo da run (run, header com modo replay/paused/live/interrupted, tarefas com evidências e tentativas, saídas em memória, operações interrompidas, eventos recentes e estatísticas); levanta `LookupError` se a run não existir.

## `src/agent/orchestrator/execution/`

**Propósito:** Execução de uma tarefa — despacho (MCP, modelo, ferramenta, verificação), contexto da operação, escrita do arquivo e evidência.

- Arquivo: [README.md](/src/agent/orchestrator/execution/README.md)
- Arquivo: [__init__.py](/src/agent/orchestrator/execution/__init__.py)
- Arquivo: [executor.py](/src/agent/orchestrator/execution/executor.py)
- Arquivo: [guards.py](/src/agent/orchestrator/execution/guards.py)
- Arquivo: [journal.py](/src/agent/orchestrator/execution/journal.py)
- Arquivo: [model_operation.py](/src/agent/orchestrator/execution/model_operation.py)
- Arquivo: [providers.py](/src/agent/orchestrator/execution/providers.py)
- Arquivo: [runtime.py](/src/agent/orchestrator/execution/runtime.py)
- Arquivo: [tool_results.py](/src/agent/orchestrator/execution/tool_results.py)
- Arquivo: [workspace.py](/src/agent/orchestrator/execution/workspace.py)
- Arquivo: [writes.py](/src/agent/orchestrator/execution/writes.py)

## `src/agent/remote/`

**Propósito:** Execução remota por SSH — quando o projeto roda em outro computador, os comandos, leituras e escritas acontecem no servidor.

- Arquivo: [README.md](/src/agent/remote/README.md)
- Arquivo: [__init__.py](/src/agent/remote/__init__.py)
- Arquivo: [ssh.py](/src/agent/remote/ssh.py)
- Arquivo: [tools.py](/src/agent/remote/tools.py)

## `src/agent/orchestrator/`

**Propósito:** Ciclo de execução: estratégia, decomposição, validação, verificação, consolidação e progresso.

- Arquivo: [README.md](/src/agent/orchestrator/README.md)
- Arquivo: [__init__.py](/src/agent/orchestrator/__init__.py)
- Subpasta: [src/agent/orchestrator/execution/](/src/agent/orchestrator/execution/)
- Arquivo: [approach.py](/src/agent/orchestrator/approach.py)
- Arquivo: [atomizer.py](/src/agent/orchestrator/atomizer.py)
- Arquivo: [closing.py](/src/agent/orchestrator/closing.py)
- Arquivo: [consolidation.py](/src/agent/orchestrator/consolidation.py)
- Arquivo: [decomposition.py](/src/agent/orchestrator/decomposition.py)
- Arquivo: [engine.py](/src/agent/orchestrator/engine.py)
- Arquivo: [global_verify.py](/src/agent/orchestrator/global_verify.py)
- Arquivo: [plan_validation.py](/src/agent/orchestrator/plan_validation.py)
- Arquivo: [planner.py](/src/agent/orchestrator/planner.py)
- Arquivo: [progress.py](/src/agent/orchestrator/progress.py)
- Arquivo: [replan.py](/src/agent/orchestrator/replan.py)
- Arquivo: [requirements.py](/src/agent/orchestrator/requirements.py)
- Arquivo: [resume.py](/src/agent/orchestrator/resume.py)
- Arquivo: [runner.py](/src/agent/orchestrator/runner.py)
- Arquivo: [stagnation.py](/src/agent/orchestrator/stagnation.py)
- Arquivo: [strategy.py](/src/agent/orchestrator/strategy.py)
- Arquivo: [usage.py](/src/agent/orchestrator/usage.py)

### `src/agent/orchestrator/README.md`

**Propósito:** Índice da pasta `orchestrator/`.

### `src/agent/orchestrator/__init__.py`

**Propósito:** Re-exporta módulos públicos.

### `src/agent/orchestrator/approach.py`

**Propósito:** guarda a memória operacional da etapa — o que foi tentado, a hipótese da falha e o que será diferente na próxima tentativa. **Quando/onde:** usado pelo diário de falhas (a cada falha registrada) e pelo construtor de contexto (a etapa seguinte recebe o bloco de abordagem no prompt).

- `_now() -> str` — Instante atual em ISO-8601 (UTC), para marcar quando a abordagem foi registrada. Entrada: nenhuma; saída: a marca de tempo.
- `alternatives_for(cause: str) -> list[str]` — Alternativas concretas para uma causa de falha, da mais próxima à mais radical (dividir, reduzir, pedir ajuda). Entrada: causa; saída: lista de alternativas (vazia quando a causa não tem alternativa conhecida).
- `approach_of(task: Any) -> dict[str, Any]` — Memória de abordagem registrada na etapa. Entrada: etapa; saída: dicionário de abordagem (vazio quando a etapa ainda não falhou).
- `approach_signature(task: Any) -> str` — Impressão da abordagem vigente: a causa e a mudança em vigor. Não inclui o detalhe do erro, que muda a cada tentativa sem que a abordagem mude. Entrada: etapa; saída: string hexadecimal (vazia sem abordagem).
- `criteria_for(cause: str) -> tuple[str, str]` — Critério de sucesso e de fracasso da próxima tentativa. Entrada: causa; saída: par (sucesso, fracasso).
- `declare_change(task: Any, description: str) -> dict[str, Any]` — Registra que a etapa vai passar a fazer outra coisa, tornando a mudança auditável. Entrada: etapa e descrição; saída: a memória depois do registro.
- `hypothesis_for(cause: str, detail: str='') -> str` — Hipótese declarada para a falha, derivada da causa de forma determinística. Entrada: causa e detalhe; saída: a hipótese em texto.
- `record_attempt(task: Any, failure: dict[str, Any], *, alternatives: list[str] | None=None) -> dict[str, Any]` — Registra a tentativa que falhou e prepara a próxima abordagem: o que travou, a hipótese, o que foi tentado, o que será diferente e os critérios de sucesso e de fracasso. Entrada: etapa e falha; saída: a memória depois do registro.
- `render_approach(task: Any) -> str` — Bloco de abordagem para o prompt da etapa: o que travou, a hipótese, o que já foi tentado, o que precisa ser diferente e os critérios. Quando a lista acaba, pede inspeção do estado antes de ação de fora. Entrada: etapa; saída: texto (vazio quando a etapa ainda não falhou).

### `src/agent/orchestrator/atomizer.py`

**Propósito:** decide de forma adaptativa quando e como uma etapa interna do plano deve ser subdividida em subetapas atômicas. **Quando/onde:** usado pelo `RunOrchestrator` durante o planejamento de uma tarefa sem filhos, quando o gatilho `atomize` está ativo ou a complexidade/tentativas justificam dividir mais.

- `adaptive_decompose_operation(objective: str, *, metadata: dict[str, Any] | None=None, lead_specialty: str | None=None, depth: int=0, max_depth: int=3) -> DecompositionResult` — Escolhe o roteiro de decomposição conforme o domínio do objetivo (bug, refatoração, documentação ou engenharia padrão) e a especialidade líder. Entrada: objetivo, metadados, `lead_specialty` e profundidade; saída: `DecompositionResult` com subetapas encadeadas por `depends_on_indices`; ao atingir `max_depth`, devolve uma única etapa atômica.
- `complexity_score(*, objective: str, metadata: dict | None, kind: str, attempt_count: int) -> int` — Pontua a complexidade da etapa: tamanho do objetivo (até +5), número de chaves de metadata, +2 para kind SUBSYSTEM/OBJECTIVE, +3 para `model_operation`, +2 a partir de 2 tentativas e +5 para o gatilho `atomize`. Entrada: objetivo, metadados, tipo e nº de tentativas; saída: inteiro comparável ao limiar de subdivisão.
- `depth_guard(*, depth: int, max_depth: int, parent_title: str='', sibling_titles: list[str] | None=None) -> str | None` — Barreira contra recursão e ciclos na decomposição recursiva: devolve o motivo do bloqueio quando a profundidade máxima é atingida ou quando o título do pai repetiria um título de etapa irmã; devolve `None` quando a decomposição pode seguir.
- `micro_decompose_operation(objective: str) -> DecompositionResult` — plano granular.
- `should_decompose_further(*, objective: str, metadata: dict | None, kind: str, attempt_count: int, has_children: bool, threshold: int=4, depth: int=0, max_depth: int=3) -> bool` — decide se divide mais (tentativas ≥ 2).

### `src/agent/orchestrator/closing.py`

**Propósito:** verifica se um texto do modelo serve como resposta utilizável e compõe o Markdown de conclusão (ou de trabalho incompleto). **Quando/onde:** usado na etapa final do run, para validar a resposta escrita pelo modelo e montar o relatório final ao usuário.

- `compose_final_markdown(*, objective: str, stages: list[dict], model_text: str='') -> str` — Monta o Markdown da resposta final a partir do objetivo, das etapas concluídas e do texto do modelo. Entradas: objetivo, estágios e texto; saída: resposta final formatada.
- `compose_incomplete_markdown(*, objective: str, pending: list[dict], reason: str, requirements: list[dict] | None=None) -> str` — Monta a resposta final quando a tarefa não foi concluída, listando pendências, o motivo e os requisitos em aberto. Entradas: objetivo, pendências, motivo e requisitos; saída: Markdown explicativo.
- `ensure_closing_stages(plan: DecompositionResult) -> DecompositionResult` — garante etapa final_answer + verificação.
- `extract_sources(*chunks: str) -> list[str]` — Extrai as fontes (caminhos de arquivo) citadas nos textos informados; devolve a lista de caminhos únicos.
- `local_now_line() -> str` — data/hora local formatada.
- `usable_markdown(text: str) -> bool` — Indica se o texto tem formato Markdown aproveitável: exige tamanho mínimo de 40 caracteres, proíbe início com `{` ou `[` (JSON de ferramenta) e exige marcadores como `#`, item de lista, separador de tabela ou bloco de código. Entrada: texto bruto; saída: booleano.
- `usable_reply(text: str) -> bool` — valida se resposta do modelo serve como final.

- `verification_footer(session, root) → str` — Fatos verificados do trabalho, em texto determinístico.
### `src/agent/orchestrator/consolidation.py`

**Propósito:** consolida bottom-up o resultado dos filhos no pai, checando evidências, pendências e casos opcionais/substituídos. **Quando/onde:** chamado pelo `RunOrchestrator` quando uma tarefa com filhos termina, e como fonte de estado (verificação, supersessão, opcionalidade) para o resto do orquestrador.

- `_walk(ts: TaskService, task_id: uuid.UUID, path: list[TaskStatus], reason: str | None=None) -> None` — Percorre a sequência de estados em `path` e aplica cada um na tarefa via `TaskService.update_status`, opcionalmente com um motivo. Entrada: serviço de tarefas, id da tarefa e caminho de estados; saída: `None` (efeito colateral no banco).
- `children_of(session: Session, parent_id: uuid.UUID) -> list[TaskModel]` — Devolve as subtarefas (filhos diretos) da tarefa informada, na ordem de criação.
- `collect_evidences(session: Session, task_id: uuid.UUID) -> list[dict[str, Any]]` — Lista as evidências registradas para a tarefa em ordem cronológica. Entrada: sessão e id da tarefa; saída: lista de dicionários com `verifier`, `passed`, `summary` e `detail`.
- `consolidate_parent(session: Session, parent_id: uuid.UUID) -> dict[str, Any] | None` — sobe resultados, `achieved`, `pending`.
- `is_optional(task: TaskModel) -> bool` — Diz se a subtarefa é opcional (falha dela não impede o pai): verifica `metadata.optional` ou `metadata.severity == "optional"`. Entrada: modelo da tarefa; saída: booleano.
- `pending_reason(task: TaskModel) -> str` — Explica por que a tarefa não concluiu: detalhe da última falha categorizada, motivo de bloqueio ou o próprio status, truncado em 300 caracteres. Entrada: modelo da tarefa; saída: string motivo.
- `settled(task: TaskModel) -> bool` — task terminal (COMPLETED/FAILED/CANCELLED).
- `superseded(task: TaskModel) -> bool` — Indica que a etapa parada foi substituída por um replanejamento (`metadata.superseded_by_replan`) e por isso deixa de contar como pendência. Entrada: modelo da tarefa; saída: booleano.
- `verification_evidence_ok(session: Session, task: TaskModel) -> bool` — evidência válida e atual.
- `verification_spec(task: TaskModel) -> dict | None` — Devolve a especificação de verificação declarada na tarefa ou, para escritas sem declaração, a verificação implícita que já rodou. Entrada: modelo da tarefa; saída: dicionário de spec ou `None`.

- `latest_verification_failed(session, task) → bool` — A verificação mais recente desta etapa reprovou (não é ausência de evidência).
- `inherits_read_only(session, task) → bool` — A tarefa (ou um de seus ancestrais) é de um pedido que proíbe alterar arquivos.
- `inherits_flag(session, task, flag) → bool` — A tarefa (ou um de seus ancestrais) carrega a marca `flag`.
- `cancelled_expected(task) → bool` — Cancelamento previsto: outra etapa assume o trabalho, o pai pode seguir.
- `dependencies_of(session, task_id) → list[TaskModel]` — Tarefas das quais esta depende, pela aresta `task_dependencies`.
- `stages_outcome(session, task) → tuple[bool | None, str, dict[str, Any]]` — Conferência das etapas anteriores: o verificador `stages` não é mais uma aprovação automática.
### `src/agent/orchestrator/decomposition.py`

**Propósito:** define o modelo de dados do plano (subtarefas) e resolve a decomposição hierárquica do objetivo, via modelo ou templates de fallback. **Quando/onde:** usado pelo `RunOrchestrator` no estado PLANNING para gerar o plano de subetapas de uma tarefa.

- `DecompositionResult(BaseModel)` — Modelo Pydantic que representa o plano como uma lista de `SubTaskSpec`. Entrada: lista de specs; saída: instância validada com o campo `subtasks`.
- `SubTaskSpec(BaseModel)` — Modelo Pydantic de uma subtarefa do plano: `title`, `objective`, `kind`, `scope`, `acceptance_criteria`, `metadata` e `depends_on_indices` (índices de subtarefas predecessoras). Entrada: campos da spec; saída: instância validada.
- `_is_page_request(objective: str) -> bool` — Detecta pedidos de página/site (site, página, html, landing, loja) que não sejam em Python. Entrada: objetivo textual; saída: booleano que decide entre o plano de página e o plano genérico.
- `align_verification(objective: str, plan: DecompositionResult) -> DecompositionResult` — troca pytest por file_contains em page requests.
- `apply_decomposition(session: Session, project_id: uuid.UUID, parent_id: uuid.UUID, plan: DecompositionResult) -> list[uuid.UUID]` — cria subtasks + deps.
- `builtin_plan_for_objective(objective: str) -> DecompositionResult | None` — plano fixo E2E.
- `direct_answer_plan(objective: str) -> DecompositionResult | None` — pergunta curta → final_answer direto.
- `executable_leaf(metadata: dict | None) -> bool` — tool/verification/model_operation/atomic/final_answer = folha.
- `fallback_plan(objective: str) -> tuple[DecompositionResult, str]` — template genérico ou page template.
- `page_plan(objective: str) -> DecompositionResult` — plano para página/site (HTML).
- `plan_copies_siblings(sibling_titles: list[str], plan_titles: list[str], current_title: str) -> bool` — detecta plano repetido.
- `plan_with_model(provider: LLMProvider, profile: ModelProfile, objective: str, context_snippet: str, *, language: str='pt', browser_mode: str='off', requirements: list[dict[str, Any]] | None=None) -> DecompositionResult | None` — Monta o prompt de decomposição (idioma, estado do navegador, contexto do projeto, bloco de requisitos, catálogo de ferramentas) e pede um JSON ao modelo via `observed_chat`. Entrada: provider, perfil, objetivo, contexto e requisitos; saída: `DecompositionResult` validado ou `None` quando a resposta não é JSON válido/sem subtarefas.
- `profile_from_run_config(run_config: dict[str, Any], settings: Settings) -> ModelProfile` — Deriva o `ModelProfile` (limite de contexto, orçamento de entrada, reserva de saída) da configuração da run e dos padrões das settings. Entradas: config e settings; saída: perfil do modelo.
- `requirements_block(requirements: list[dict[str, Any]] | None) -> str` — Monta o bloco de texto com os requisitos que o plano precisa cobrir e instrui o modelo a declarar `metadata.covers` em cada subtarefa. Entrada: lista de requisitos; saída: string (vazia quando não há requisitos).
- `automation_plan(objective: str) -> DecompositionResult` — Plano fixo de uma etapa para pedidos sobre tarefas agendadas.
- `resolve_decomposition_plan(*, settings: Settings, run_config: dict[str, Any], objective: str, project_root: str, provider: LLMProvider | None=None, requirements: list[dict[str, Any]] | None=None, previous_objectives: list[str] | None=None) -> tuple[DecompositionResult | None, str]` — builtin e2e → automação → modelo → template genérico → mock; `previous_objectives` traz o contexto da conversa.
- `seal_repeated_steps(parent_title: str, plan: DecompositionResult) -> DecompositionResult` — filho com mesmo título do pai vira model_operation.

- `norm(items) → list[str]` — Normaliza uma lista de títulos para comparação.

- `_supports_tool_loop(provider) → bool` — O provedor sabe manter a conversa de ferramentas? (mesma regra do orquestrador.).
### `src/agent/orchestrator/engine.py`

**Propósito:** esqueleto explícito do ciclo de orquestração, capable de promover e iniciar tarefas. **Quando/onde:** usado como ciclo mínimo de coordenação de status (base para as fases seguintes), independente do `RunOrchestrator` completo.

- `OrchestratorEngine` — Coordenação explícita da transição de estados das tarefas, expandível com decomposição, ferramentas e verificação. Entrada: sessão do SQLAlchemy via `__init__`; saída: ações do ciclo em `tick`.
- `OrchestratorEngine.__init__(session: Session) -> None` — Inicializa o motor guardando um `TaskService` ligado à sessão. Entrada: sessão; saída: `None`.
- `OrchestratorEngine.tick(task_id: uuid.UUID) -> dict` — Executa um passo do ciclo: promove PLANNING→READY quando as dependências estão satisfeitas, senão move READY→RUNNING; devolve `{"action": ...}` com a ação aplicada ou `noop` com o status atual. Entrada: id da tarefa; saída: dicionário de ação.

### `src/agent/orchestrator/global_verify.py`

**Propósito:** avalia os critérios globais de conclusão do objetivo (evidências válidas e requisitos obrigatórios comprovados) e reabre o que ficou sem prova. **Quando/onde:** usado pelo `RunOrchestrator` quando o run chega ao fim das tarefas para aceitar ou reabrir o resultado.

- `_gap_failure(session: Session, task: TaskModel) -> Failure` — Classifica a falha de evidência da tarefa: `STALE_EVIDENCE` quando os arquivos verificados mudaram depois da verificação, senão `VERIFICATION_FAILED`. Entrada: sessão e tarefa; saída: `Failure` recuperável com a causa e o detalhe.
- `_reopen(ts: TaskService, task: TaskModel, reason: str) -> None` — Reabre uma tarefa concluída, levando-a de COMPLETED a VERIFYING e depois PLANNING com o motivo. Entrada: serviço de tarefas, tarefa e motivo; saída: `None`.
- `_subtree_tasks(session: Session, root_id: uuid.UUID) -> list[TaskModel]` — Devolve todas as tarefas da subárvore da raiz, fechando a relação `parent_id` iterativamente. Entrada: sessão e id da raiz; saída: lista de `TaskModel`.
- `correct_requirement_gaps(session: Session, root: TaskModel) -> list[uuid.UUID]` — cria etapas `Atender Rn`/`Comprovar Rn`.
- `ensure_global_verification_task(session: Session, project_id: uuid.UUID, root: TaskModel) -> TaskModel | None` — cria etapa se faltar.
- `evaluate_global_acceptance(session: Session, root_id: uuid.UUID) -> tuple[bool, str]` — todos requisitos `satisfied`?
- `invalidate_latest(session: Session, task_id: uuid.UUID, reason: str) -> None` — Marca a evidência mais recente como `desatualizado` (estado anterior, momento e motivo), sem apagá-la. Entrada: sessão, id da tarefa e motivo; saída: `None` (a evidência permanece no banco).
- `reopen_verification_gaps(session: Session, root_id: uuid.UUID) -> list[uuid.UUID]` — reabre tasks com evidência reprovada/desatualizada.
- `requirements_report(session: Session, root: TaskModel) -> list[dict]` — status de cada requisito.
- `unmet_requirements(report: list[dict]) -> list[dict]` — Filtra do relatório os requisitos que não são `satisfied`, `não aplicável` ou `informativo`. Entrada: relatório de requisitos; saída: lista dos requisitos não atendidos.

### `src/agent/orchestrator/disposition.py`

**Propósito:** escolhe executar, investigar, decompor ou replanejar antes de subdividir uma etapa já marcada com `atomize`. **Quando/onde:** o `RunOrchestrator` usa no planejamento quando a etapa pede atomização e ainda não gastou duas tentativas.

- `Disposition` — Decisão com `action`, `reason` e `factors`. Entrada: os três campos; saída: objeto serializável.
- `Disposition.as_dict() -> dict[str, Any]` — Serializa a decisão para o metadado da tarefa. Entrada: a própria decisão; saída: dicionário.
- `decide_disposition(*, objective: str, metadata: dict[str, Any] | None, depth: int, max_depth: int, attempt_count: int, strategy: dict[str, Any] | None=None) -> Disposition` — Escolhe o modo da etapa pela ordem fixa: passo fechado, profundidade de proteção, falha repetida, falta de contexto, várias partes ou objetivo único. Entrada: objetivo, metadados, profundidade, tentativas e estratégia; saída: `Disposition`.
- `investigation_plan(objective: str, *, read_only: bool=False) -> DecompositionResult` — Plano curto que lista o diretório antes de agir e só verifica quando o pedido muda arquivo. Entrada: objetivo e flag de leitura; saída: `DecompositionResult`.

### `src/agent/orchestrator/language_strategy.py`

**Propósito:** escolher o idioma operacional sem traduzir por modelo e sem perder o pedido original. **Quando/onde:** no primeiro passo da raiz; o quadro entra no prompt de decomposição e da operação; a filha herda o contrato.

- `_sentences(text: str) -> list[str]` — Parte o pedido em frases. Entrada: texto; saída: lista de frases.
- `apply_operational_text(original: str, translated: str | None) -> tuple[str, str]` — Aceita o texto operacional só se literal, número e restrição continuam presentes. Entrada: pedido e candidato; saída: texto mantido e motivo do fallback.
- `build_language_contract(objective: str, *, mode: str='auto', presentation: str='auto', profile: dict[str, Any] | None=None) -> dict[str, Any]` — Monta o contrato com idiomas de entrada, operação e apresentação. Entrada: pedido, modo, apresentação e perfil; saída: contrato compacto.
- `compare_strategies(objective: str) -> dict[str, str]` — Aplica os três modos ao mesmo pedido. Entrada: pedido; saída: estratégia aplicada por modo. Não mede qualidade.
- `explain_language(contract: dict[str, Any] | None) -> str` — Frase do feed no idioma de apresentação quando a operação usa inglês. Entrada: contrato; saída: frase ou vazia.
- `extract_ambiguities(text: str) -> list[str]` — Frases com alternativa ou incerteza, sem resolvê-las. Entrada: pedido; saída: frases.
- `extract_constraints(text: str) -> list[str]` — Frases de restrição copiadas do pedido. Entrada: pedido; saída: frases.
- `extract_literals(text: str) -> list[str]` — Caminhos, crases, URLs e identificadores. Entrada: pedido; saída: literais.
- `extract_numbers(text: str) -> list[str]` — Números na grafia original. Entrada: pedido; saída: números.
- `fidelity_gaps(original: str, operational: str) -> list[str]` — Lista o que a representação perdeu. Entrada: pedido e candidato; saída: lacunas.
- `inherit_language(contract: dict[str, Any] | None) -> dict[str, Any] | None` — Recorte do contrato para a filha, sem traduzir de novo. Entrada: contrato do pai; saída: recorte ou `None`.
- `render_operational_for_prompt(metadata: dict[str, Any] | None) -> str` — Quadro em inglês para o modelo, com restrições e literais intactos. Entrada: metadados; saída: texto ou vazio.
- `select_applied(mode: str, *, input_language: str, objective: str, profile: dict[str, Any] | None=None) -> str` — Escolhe `native` ou `english_operational`. Entrada: modo, idioma, pedido e perfil; saída: estratégia aplicada.
- `switch_language(metadata: dict[str, Any] | None, cause: str) -> dict[str, Any] | None` — Depois de saída inválida, volta ao idioma original uma vez. Entrada: metadados e causa; saída: contrato novo ou `None`.

### `src/agent/orchestrator/narration.py`

**Propósito:** monta a frase do feed a partir do contrato e da decisão, sem chamar o modelo. **Quando/onde:** o orquestrador publica `work.explained` no início da raiz e ao definir ou aplicar um plano.

- `explain_quality(contract: dict[str, Any] | None) -> str` — Resume pedido explícito, piso inferido e incerteza, sem marcar critério como verificado. Entrada: contrato ou `None`; saída: frase redigida, ou vazia.
- `explanation_event(category: str, text: str, *, phase: str) -> dict[str, str] | None` — Monta o payload de `work.explained` se a categoria e o texto forem válidos. Entrada: categoria, texto e fase; saída: payload ou `None`.
- `safe_explanation(text: str | None, *, limit: int=400) -> str` — Redige segredo e trunca a frase. Entrada: texto e limite; saída: texto publicável, ou vazio.

### `src/agent/orchestrator/quality_contract.py`

**Propósito:** separa o que o usuário pediu, o piso profissional do domínio, as premissas e o que fica de fora. **Quando/onde:** gravado no aceite da raiz no primeiro passo de planejamento e herdado pelas filhas.

- `_items(text: str) -> list[str]` — Extrai itens enumerados do pedido. Entrada: texto; saída: lista de itens.
- `_profile_for(domain: str, objective: str) -> tuple[str, list[str]]` — Escolhe o perfil de qualidade do domínio, trocando para web quando o pedido é de interface. Entrada: domínio e objetivo; saída: nome do perfil e critérios.
- `attach_quality_contract(session: Session, task: TaskModel, contract: dict[str, Any]) -> dict[str, Any]` — Grava o contrato em `acceptance_json.quality` sem apagar os requisitos já existentes. Entrada: sessão, tarefa e contrato; saída: contrato gravado.
- `build_quality_contract(objective: str, strategy: ProfessionalStrategy | dict[str, Any] | None) -> dict[str, Any]` — Monta o contrato com origem explícita, inferida ou premissa, teto de protótipo e critérios pendentes. Entrada: objetivo e estratégia; saída: dicionário do contrato.
- `compact_quality(contract: dict[str, Any]) -> dict[str, Any]` — Recorta o contrato para caber no metadado da tarefa. Entrada: contrato completo; saída: recorte.
- `inherit_quality(parent: dict[str, Any] | None, child_objective: str) -> dict[str, Any] | None` — Leva à filha restrições, exclusões e critérios relacionados, sem premissas nem histórico. Entrada: contrato do pai e objetivo da filha; saída: recorte ou `None`.
- `render_quality_for_prompt(metadata: dict[str, Any] | None) -> str` — Texto curto dos critérios herdados para o prompt, com premissa marcada como não confirmada. Entrada: metadados; saída: bloco de texto ou vazio.

### `src/agent/orchestrator/plan_validation.py`

**Propósito:** valida de forma determinística o plano de subtarefas antes da execução, repara o que é seguro e decide se o plano pode rodar. **Quando/onde:** chamado pelo `RunOrchestrator` logo após decompor e antes de executar as etapas, e de novo quando o plano muda.

- `Issue` — Dataclass que representa um problema do plano: `code`, `verdict` (PlanVerdict), `message` e `task_id` opcional da etapa afetada. Entrada: campos da issue; saída: registro estruturado usado no relatório de validação.
- `PlanValidation` — Resultado da validação do plano: veredito, problemas encontrados, correções aplicadas, cobertura, fingerprint e estado bloqueante.
- `PlanValidation.as_dict() -> dict[str, Any]` — Serializa a validação para dicionário, convertendo o veredito e as issues para os valores textuais dos enums. Entrada: instância de `PlanValidation`; saída: dicionário JSON-serializável.
- `PlanValidation.runnable() -> bool` — Indica se o plano pode ser executado: verdicts `válido`, `válido com ressalvas` e `inconclusivo` são considered runnable. Entrada: instância; saída: booleano.
- `PlanVerdict(StrEnum)` — Enum de veredictos do plano (`válido`, `válido com ressalvas`, `inconclusivo`, `incompleto`, `inconsistente`, `inviável`), ordenados por gravidade. Entrada: valor do enum; saída: string comparável.
- `_cancel(ts: TaskService, task: TaskModel, reason: str) -> None` — Cancela a tarefa com o motivo quando ela está em PENDING, PLANNING, READY, RETRY_PENDING ou BLOCKED. Entrada: serviço de tarefas, tarefa e motivo; saída: `None`.
- `_dependency_issues(session: Session, kids: list[TaskModel]) -> list[Issue]` — Analisa as dependências entre as etapas do plano e aponta dependência inexistente, de outro projeto, de tarefa cancelada ou circular. Entrada: sessão e filhos; saída: lista de `Issue`.
- `_duplicate_issues(kids: list[TaskModel]) -> list[Issue]` — Deteta etapas repetidas exatamente (título, objetivo, ferramenta e args) ou com o mesmo título. Entrada: filhos; saída: lista de `Issue`.
- `_norm(text: str | None) -> str` — Normaliza texto para comparação: colapsa espaços e aplica `casefold`. Entrada: texto possivelmente nulo; saída: string normalizada.
- `_produced_before(session: Session, task: TaskModel, path: str) -> bool` — Verifica se alguma dependência anterior da etapa cria o caminho lido (operação de modelo, tool_args ou objetivo). Entrada: sessão, tarefa e caminho; saída: booleano.
- `_reaches(graph: dict[int, set[int]], start: int, target: int) -> bool` — Percorre em profundidade o grafo de dependências por índice para detectar ciclos. Entrada: grafo e nós; saída: booleano de alcançabilidade.
- `_reaches_ids(graph: dict[uuid.UUID, set[uuid.UUID]], start: uuid.UUID, target: uuid.UUID) -> bool` — Mesma verificação de alcançabilidade, mas sobre o grafo de dependências por uuid de tarefa. Entrada: grafo e ids; saída: booleano.
- `_subtree_ids(session: Session, root: TaskModel) -> set[uuid.UUID]` — Devolve o conjunto de ids de todas as tarefas descendentes da raiz, no mesmo projeto. Entrada: sessão e tarefa raiz; saída: conjunto de UUIDs.
- `_verifiable(task: TaskModel) -> bool` — Diz se a etapa tem critério verificável (verificação, resposta final, operação de modelo, subsystem ou critérios de aceite preenchidos). Entrada: modelo da tarefa; saída: booleano.
- `active_children(session: Session, parent_id: uuid.UUID) -> list[TaskModel]` — Devolve as subtarefas ativas (não canceladas) da tarefa informada — a base das regras de validação e do plano.
- `plan_fingerprint(session: Session, parent_id: uuid.UUID) -> str` — hash do plano (títulos, kinds, tools, covers, deps).
- `record_validation(session: Session, parent: TaskModel, validation: PlanValidation, run_id: uuid.UUID | None) -> None` — Grava o estado atual da validação em `metadata.plan_validation` (com versão incremental) e registra um evento `plan.validated` com a versão e o plano. Entrada: sessão, pai, validação e run; saída: `None`.
- `repair_plan(session: Session, parent: TaskModel, validation: PlanValidation) -> list[str]` — Aplica correções automáticas seguras (cancelar duplicatas, remover dependências inválidas, trocar ferramenta inexistente por operação de modelo, criar etapa para requisito sem responsável). Entrada: sessão, pai e validação; saída: lista com a descrição de cada correção aplicada.
- `sanitize_spec(plan: DecompositionResult) -> tuple[DecompositionResult, list[Issue]]` — remove deps inválidas, cancela duplicatas.
- `summarize(validation: PlanValidation, limit: int=4) -> str` — texto para failure.
- `validate_and_repair(session: Session, parent: TaskModel, *, project_root: str, run_config: dict[str, Any] | None, max_tasks: int | None, run_id: uuid.UUID | None, extra_issues: list[Issue] | None=None) -> PlanValidation` — Valida o plano da tarefa contra as regras determinísticas e o repara quando possível (sanitiza dependências, cancela duplicatas, corrige cobertura); devolve a `PlanValidation` com veredito e correções.
- `validate_children(session: Session, parent: TaskModel, *, project_root: str, run_config: dict[str, Any] | None=None, max_tasks: int | None=None, extra_issues: list[Issue] | None=None) -> PlanValidation` — Aplica todas as regras estruturais do plano: objetivo e critérios, cobertura de requisitos, ferramentas inexistentes ou bloqueadas, arquivos de entrada ausentes, duplicatas, dependências e orçamento de tarefas. Entrada: sessão, tarefa pai e parâmetros de execução; saída: `PlanValidation` com veredito, issues, cobertura, etapas bloqueadas e fingerprint do plano.

- `repair_steps(session, parent, validation) → list[str]` — Correções locais de etapa: a etapa passa a fazer o que é possível fazer.

- `_anchor_present(project_root, path, anchor) → bool` — O trecho que a edição pretende substituir existe no arquivo?.
### `src/agent/orchestrator/planner.py`

**Propósito:** Memória canônica do objetivo.

- `ensure_canonical_memory_for_objective(session: Session, project_id: uuid.UUID, root_task: TaskModel) -> None` — grava "Objetivo global" + memória da conversa.

### `src/agent/orchestrator/progress.py`

**Propósito:** calcula progresso verificável a partir do estado persistido das tarefas, e não do número de chamadas. **Quando/onde:** usado pelo `RunOrchestrator` para medir o progresso do run, detectar estagnação e decidir se houve avanço real.

- `made_progress(before: dict[str, int] | None, after: dict[str, int]) -> bool` — mais verificados ou menos pendentes sem perder verificados.
- `progress_state(session: Session, root_id: uuid.UUID) -> dict[str, int]` — `{verified, pending, blocked, total}`.
- `subtree(session: Session, root_id: uuid.UUID) -> list[TaskModel]` — Devolve todas as tarefas da subárvore da raiz, fechando a relação `parent_id` iterativamente dentro do mesmo projeto. Entrada: sessão e id da raiz; saída: lista de `TaskModel`.

### `src/agent/orchestrator/recovery_policy.py`

**Propósito:** decidir se a falha segue, pede uma investigação, pausa ou para porque a condição é externa. **Quando/onde:** o replanejamento e a estagnação leem esta política; a frase do feed sai daqui sem chamar o modelo.

- `alternative_continuance(approach: dict[str, Any] | None) -> str` — `continue` enquanto houver alternativa, `investigate` uma vez quando a lista acaba, `pause` depois dessa investigação. Entrada: memória de abordagem; saída: uma dessas três palavras.
- `mark_open_investigation(task: Any) -> dict[str, Any]` — Grava na etapa o passo de inspeção, preserva `tried` e muda a assinatura. Entrada: etapa; saída: memória atualizada.
- `may_have_partial_effect(cause: str) -> bool` — Indica timeout, indisponibilidade, erro de provedor ou limite de taxa, casos em que a resposta pode ter se perdido depois de um efeito. Entrada: causa; saída: booleano.
- `narrate_failure(category: str, cause: str, detail: str) -> str` — Frase do feed para a falha já classificada, sem anunciar sucesso. Entrada: categoria, causa e detalhe; saída: texto curto.
- `pause_next_action(*, total: int, run_id: Any, probable_cause: str) -> str` — Texto da pausa quando o orçamento acaba sem prova de impossibilidade, com o caminho de retomada. Entrada: total, run e causa; saída: próxima ação.
- `root_should_recover(*, has_parent: bool, already_recovered: bool, replan: bool) -> bool` — A raiz sem pai volta a planejar uma vez quando o replanejamento ainda cabe. Entrada: as três flags; saída: booleano.

### `src/agent/orchestrator/replan.py`

**Propósito:** revisa o plano do pai quando uma etapa para no meio, conforme orçamento e progresso, sem refazer o que já foi concluído. **Quando/onde:** chamado pelo `RunOrchestrator` no início de cada passo, antes de escolher a próxima tarefa.

- `ReplanDecision` — Dataclass imutável com o veredito `replan` e o `reason` da recusa ou da decisão. Entrada: campos da decisão; saída: registro consultado pela política de replanejamento.
- `_carried_covers(session: Session, kids: list[TaskModel], stopped: TaskModel) -> list[dict] | None` — Funde a cobertura de requisitos da etapa parada e das irmãs ainda pendentes para que o plano corrigido não perca requisito; devolve `None` quando o plano não declara cobertura. Entrada: sessão, filhos e etapa parada; saída: lista de coberturas ou `None`.
- `replan_decision(parent_meta: dict, stopped: TaskModel, completed: int) -> ReplanDecision` — Decide se replaneja. Recusa ação externa, orçamento da linhagem e repetição sem progresso. Lista de alternativas esgotada ainda autoriza uma investigação; a segunda vez pausa.
- `replan_parent(session: Session, parent: TaskModel) -> dict | None` — Reescreve o plano do pai cujo filho parou: cancela as etapas irrecuperáveis, marca a parada como substituída, cria o plano corrigido e registra o histórico. Entrada: sessão e tarefa pai; saída: dicionário com `action`, `task_id`, `stopped_at` e `cancelled`, ou `None` quando não cabe replanejar.
- `replan_under(session: Session, root_id: uuid.UUID) -> dict | None` — replaneja se diagnóstico novo em `metadata.stagnation`.

### `src/agent/orchestrator/requirements.py`

**Propósito:** extrai e mantém os requisitos do objetivo original, controla a cobertura declarada por tarefa e calcula o estado de cada requisito por evidência. **Quando/onde:** usado na raiz do run para estabilizar os ids dos requisitos e, ao final, para aceitar ou reabrir o trabalho.

- `_answered(task: TaskModel) -> bool` — Indica se a tarefa já entregou resposta final com Markdown não vazio em `consolidated_result_json`. Entrada: modelo da tarefa; saída: booleano.
- `_items(text: str | None) -> list[str]` — Extrai os itens de lista (marcadores `-`/`*`/`•` ou numeração) de um texto. Entrada: texto; saída: lista de itens.
- `_passed_current(session: Session, task_id: uuid.UUID) -> list[EvidenceModel]` — Lista as evidências da tarefa que passaram e cujo fingerprint de artefatos ainda é atual. Entrada: sessão e id da tarefa; saída: lista de `EvidenceModel`.
- `_subtree(session: Session, root: TaskModel) -> list[TaskModel]` — Devolve as tarefas descendentes da raiz, no mesmo projeto, fechando a relação `parent_id` iterativamente. Entrada: sessão e tarefa raiz; saída: lista de `TaskModel`.
- `derive_requirements(objective: str, acceptance_criteria: str | None=None) -> list[dict[str, Any]]` — Deriva requisitos determinísticos (R1..Rn) dos itens enumerados do objetivo e das linhas dos critérios de aceite; sem itens, o objetivo inteiro vira R1. Entrada: objetivo e critérios; saída: lista de requisitos com descrição, origem, critério e tipo de evidência.
- `effective_covers(session: Session, task: TaskModel, reqs: list[dict[str, Any]] | None=None) -> list[dict[str, Any]]` — covers declarados ou herdados do pai.
- `ensure_requirements(session: Session, root: TaskModel) -> list[dict[str, Any]]` — deriva do contrato/objetivo + grava no contrato.
- `evidence_kind(text: str) -> str` — Classifica o tipo de evidência exigida: `change` quando o texto indica alteração de código/arquivo (exige verificador) e `answer` quando basta a resposta final verificada. Entrada: texto; saída: `"change"` ou `"answer"`.
- `load_requirements(session: Session, root: TaskModel) -> list[dict[str, Any]]` — Lê puramente os requisitos gravados no contrato da raiz, sem derivar nem gravar. Entrada: sessão e raiz; saída: lista normalizada de requisitos (vazia se não houver contrato).
- `normalize_covers(raw: Any) -> list[dict[str, Any]] | None` — Normaliza a declaração de cobertura (`["R1", {"req": "R2", "partial": true, "part": "API"}]`) em lista uniforme de `{req, partial, part}`; devolve `None` quando nada foi declarado. Entrada: valor cru de `metadata.covers`; saída: lista normalizada ou `None`.
- `normalize_requirement(raw: dict[str, Any], index: int) -> dict[str, Any]` — Normaliza um requisito cru: id, descrição, origem, critério, aplicabilidade, tipo de evidência e referências, com defaults seguros. Entrada: dicionário bruto e índice; saída: dicionário de requisito normalizado.
- `requirement_status(session: Session, root: TaskModel) -> list[dict[str, Any]]` — uncovered/failed/pending/unverified/satisfied/não_aplicável.
- `root_of(session: Session, task: TaskModel) -> TaskModel` — sobe até raiz (parent_id=None).
- `siblings_declare_covers(session: Session, task: TaskModel) -> bool` — Diz se alguma tarefa irmã da mesma fase declara `covers`, o que torna a tarefa sem declaração uma etapa de apoio. Entrada: sessão e tarefa; saída: booleano.

- `_verification_rejected(session, task) → bool` — A etapa **concluiu** e a verificação mais recente reprovou.
- `_unproven_by_superseded(session, root, reqs, req_id, live_coverers) → bool` — Uma etapa substituída tinha uma verificação que reprovou e ninguém a refez.
### `src/agent/orchestrator/resume.py`

**Propósito:** identifica onde a tarefa parou, o que ainda falta e retoma o run pausado sem refazer o trabalho já feito. **Quando/onde:** usado pela API de retomada (`POST /runs/{id}/resume`) e na preparação de briefings de continuação.

- `_reason(task: TaskModel) -> str` — Extrai o motivo da parada: erro do resultado consolidado, `blocked_reason` dos metadados ou o próprio status, truncado em 240 caracteres. Entrada: modelo da tarefa; saída: string motivo.
- `apply_resume(session: Session, root: TaskModel, brief: dict) -> ExecutionRunModel | None` — Aplica a retomada: substitui o objetivo da raiz pela instrução corrigida (guardando o anterior), grava a memória "Retomada" e reativa o run pausado em modo autônomo. Entrada: sessão, raiz e briefing; saída: o `ExecutionRunModel` reativado ou `None` se não houver run pausado.
- `build_resume_brief(session: Session, root: TaskModel) -> dict` — Monta o briefing de retomada com o que já foi concluído, o que falta, onde parou, o motivo e uma instrução corrigida que não refaz o trabalho anterior. Entrada: sessão e raiz; saída: dicionário `brief` com `done`, `missing`, `reason`, `corrected_instruction` e `can_continue`.
- `resume_root(session: Session, task_id: uuid.UUID, *, apply: bool) -> dict` — pendências, feito, faltando, próxima ação.

### `src/agent/orchestrator/runner.py`

**Propósito:** implementa o ciclo completo de execução do run — decomposição, execução de ferramentas e do modelo, verificação, replanejamento, estagnação e fechamento. **Quando/onde:** é o orquestrador principal, acionado pela API de execução de runs e pelo avanço de cada passo (`step`/`run_until_idle`).

- `RunBlockedError(RuntimeError)` — Exceção de domínio para sinalizar que a execução foi bloqueada de forma recuperável. Entrada: mensagem; saída: erro levantado ao chamador.
- `RunOrchestrator` — Orquestrador do run: coordena status das tarefas, provider, ferramentas, tentativas, validação de plano, verificação e memória. Entrada: sessão do SQLAlchemy e `Settings` via `__init__`; saída: o dicionário de ação de cada passo.
- `RunOrchestrator.__init__(session: Session, settings: Settings | None=None) -> None` — Inicializa o orquestrador com a sessão, as configurações, o `TaskService`, o `AttemptService` (limite de tentativas) e o registro de ferramentas. Entrada: sessão e configurações opcionais; saída: `None`.
- `RunOrchestrator._all_terminal_under(root_id: uuid.UUID) -> bool` — Verifica se todas as descendentes da raiz já estão em estado terminal (completed, cancelled ou failed), ignorando a própria raiz. Entrada: id da raiz; saída: booleano.
- `RunOrchestrator._block_invalid_plan(parent: TaskModel, validation: PlanValidation) -> dict[str, Any]` — Bloqueia o pai quando o plano não pôde ser corrigido: classifica a falha (externo, limite operacional ou mudança de estratégia), move a tarefa para BLOCKED pela tabela de transições e devolve a ação `plan_invalid`. Entrada: pai e validação; saída: dicionário de ação com veredito e falha.
- `RunOrchestrator._capture_outcome_memory(project: ProjectModel, root: TaskModel) -> None` — Grava a memória contextual "Resultado da conversa" com objetivo e resposta final da raiz, evitando duplicar. Entrada: projeto e raiz; saída: `None`.
- `RunOrchestrator._check_stagnation(run_id: uuid.UUID, out: dict[str, Any]) -> dict[str, Any] | None` — Reage à repetição da mesma falha: replaneja o pai, faz a raiz sem pai planejar de novo uma vez, pausa quando o orçamento acaba sem prova de impossibilidade, ou encerra quando a causa pede ação externa. Entrada: id do run e saída do passo; saída: dicionário de ação ou `None` quando ainda não há estagnação.
- `RunOrchestrator._depth(task: TaskModel) -> int` — Calcula a profundidade da tarefa na árvore, contando os ancestrais. Entrada: modelo da tarefa; saída: inteiro de profundidade.
- `RunOrchestrator._ensure_final_message(root: TaskModel) -> None` — Garante que a raiz tenha uma resposta final: reaproveita o Markdown da etapa `final_answer` ou compõe um relatório com as etapas filhas. Entrada: raiz; saída: `None` (resultado consolidado atualizado).
- `RunOrchestrator._explain(task: TaskModel, *, category: str, text: str, phase: str) -> None` — Publica `work.explained` com a frase já redigida. Se o evento falhar, a etapa segue. Entrada: tarefa, categoria, texto e fase; saída: `None`.
- `RunOrchestrator._note_thought(run: ExecutionRunModel, task: TaskModel | None, text: str, *, phase: str='thinking', category: str | None=None) -> None` — Registra o que está acontecendo como `agent.thought` e publica a mesma frase em `work.explained` quando a categoria é válida. Entrada: run, tarefa opcional, texto, fase e categoria; saída: `None`.
- `RunOrchestrator._pause_run(run: ExecutionRunModel, root: TaskModel, hit: dict[str, Any], next_action: str, *, diagnosis: dict[str, Any] | None=None) -> dict[str, Any]` — Pausa o run (retomável) ao atingir um limite, gravando estado, pendências, requisitos, motivo e próxima ação na raiz e no evento `run.paused`, sem mudar o estado das tarefas. Entrada: run, raiz, limite atingido e próxima ação; saída: dicionário de ação `run_paused`.
- `RunOrchestrator._pending_under(root_id: uuid.UUID) -> list[dict[str, Any]]` — Lista as folhas pendentes sob a raiz (não concluídas, não assentadas e sem filhos), com título, status e motivo. Entrada: id da raiz; saída: lista de dicionários de pendência.
- `RunOrchestrator._pick_next_task(root_id: uuid.UUID) -> TaskModel | None` — Escolhe a próxima tarefa a executar por prioridade de status (running, verifying, ready, retry_pending, planning, pending), respeitando dependências e filhos não assentados. Entrada: id da raiz; saída: `TaskModel` ou `None` quando nada pode avançar.
- `RunOrchestrator._promote_ready_or_block(task_id: uuid.UUID) -> dict[str, Any] | None` — Valida o contrato da tarefa: se estiver válido, move para READY; caso contrário, move para BLOCKED com os erros e devolve a ação `blocked_contract`. Entrada: id da tarefa; saída: dicionário de bloqueio ou `None`.
- `RunOrchestrator._propagate_strategy(parent: TaskModel, plan: Any) -> None` — Repassa aos filhos a especialidade líder, o gatilho `atomize` (quando a estratégia é complexa), os requisitos da estratégia e o recorte do contrato de qualidade. Entrada: pai e plano; saída: `None` (metadados dos filhos atualizados).
- `RunOrchestrator._record_action(run_id: uuid.UUID, out: dict[str, Any]) -> None` — Registra o evento `orchestrator.action` com a saída do passo e emite `run.progress` quando o estado de progresso muda. Entrada: id do run e dicionário de saída; saída: `None`.
- `RunOrchestrator._record_quality(run: ExecutionRunModel, task: TaskModel, strategy: Any) -> None` — Grava o contrato de qualidade da raiz no aceite e no metadado e publica o resumo no feed. Uma falha aqui não impede o planejamento. Entrada: run, tarefa e estratégia; saída: `None`.
- `RunOrchestrator._record_language(run: ExecutionRunModel, task: TaskModel) -> None` — Grava o contrato linguístico da raiz e publica a frase no idioma de apresentação quando a operação usa inglês. Não chama o modelo. Entrada: run e tarefa; saída: `None`.
- `RunOrchestrator._recursion_guard(run: ExecutionRunModel, task: TaskModel) -> str | None` — Protege contra recursão: bloqueia quando a etapa repete título/objetivo de um ancestral, excede `max_tree_depth` ou o run atinge `max_tasks_per_run`. Entrada: run e tarefa; saída: motivo do bloqueio ou `None`.
- `RunOrchestrator._remember_failure(task: TaskModel, failure: Failure) -> dict[str, Any]` — Guarda a falha na tarefa (histórico `failures` e `last_failure`) com a assinatura do erro e da estratégia, para a próxima tentativa e o replanejamento lerem. Entrada: tarefa e `Failure`; saída: dicionário da falha registrada.
- `RunOrchestrator._revalidate_plan(run: ExecutionRunModel, task: TaskModel, config: dict[str, Any], work_root: str) -> dict[str, Any] | None` — Antes de executar a etapa, compara o fingerprint do plano do pai com o da última validação e revalida se mudou (replanejamento, dependência ou cobertura). Entrada: run, tarefa, configuração e raiz de trabalho; saída: dicionário de revalidação/bloqueio ou `None`.
- `RunOrchestrator._run_as_leaf(run: ExecutionRunModel, task: TaskModel, *, note: str) -> dict[str, Any]` — Executa a etapa como folha, sem nova divisão: garante operação atômica, publica a nota no feed, verifica dependências e promove para READY ou aguarda. Entrada: run, tarefa e nota de pensamento; saída: dicionário de ação.
- `RunOrchestrator._run_config(run: ExecutionRunModel) -> dict` — Devolve a configuração persistida do run. Entrada: modelo do run; saída: dicionário de configuração.
- `RunOrchestrator._same_title_above(task: TaskModel) -> bool` — Verifica se algum ancestral tem o mesmo título ou o mesmo objetivo normalizado da tarefa. Entrada: modelo da tarefa; saída: booleano.
- `RunOrchestrator._stall_run(run: ExecutionRunModel, root: TaskModel, reason: str) -> dict[str, Any]` — Encerra o run como falho quando nada pode avançar: bloqueia a raiz, salva o relatório com pendências e requisitos e emite `run.failed`. Entrada: run, raiz e motivo; saída: dicionário de ação `run_stalled`.
- `RunOrchestrator._step_body(run_id: uuid.UUID) -> dict[str, Any]` — Corpo do passo: checa limites, replaneja, escolhe a tarefa, e conforme o status avança planejamento, promoção, execução ou verificação, fechando o run quando o aceite global é aprovado. Entrada: id do run; saída: dicionário de ação do passo.
- `RunOrchestrator._subtree_ids(root_id: uuid.UUID, tasks: list[TaskModel]) -> set[uuid.UUID]` — Devolve os ids de todas as descendentes da raiz, fechando a relação `parent_id` iterativamente sobre a lista de tarefas dada. Entrada: id da raiz e lista de tarefas; saída: conjunto de UUIDs.
- `RunOrchestrator._conversation_objectives(task: TaskModel, limit: int=5) -> list[str]` — Pedidos anteriores da mesma conversa, do mais recente ao mais antigo; é o que permite reconhecer uma confirmação como resposta a um pedido de automação.
- `RunOrchestrator._task_requirements(task: TaskModel) -> list[dict]` — Lista os requisitos obrigatórios que a etapa precisa atender, combinando os requisitos da raiz com a cobertura herdada da tarefa. Entrada: modelo da tarefa; saída: lista de requisitos com marcação de parcial.
- `RunOrchestrator._validate_plan(run: ExecutionRunModel, parent: TaskModel, config: dict[str, Any], work_root: str, spec_issues: list | None=None) -> PlanValidation` — Valida o plano do pai e o repara quando possível, usando o limite de tarefas das configurações. Entrada: run, pai, configuração, raiz de trabalho e issues extras da spec; saída: `PlanValidation`.
- `RunOrchestrator._work_root(project: ProjectModel, task: TaskModel | None) -> str` — Calcula a raiz de trabalho efetiva do projeto, considerando a conversa da tarefa. Entrada: projeto e tarefa opcional; saída: caminho da raiz de trabalho.
- `RunOrchestrator.run_until_idle(run_id: uuid.UUID, max_steps: int=50) -> list[dict]` — Avança o run em sequência até alcançar um estado terminal, pausado ou bloqueado, ou até o limite de passos, acumulando o log de ações. Entrada: id do run e número máximo de passos; saída: lista de dicionários de ação.
- `RunOrchestrator.step(run_id: uuid.UUID) -> dict[str, Any]` — Executa um passo completo do run sob observação: chama o corpo do passo, verifica estagnação e registra a ação no log de eventos. Entrada: id do run; saída: dicionário de ação do passo.
- `_profile_from_config(run_config: dict, settings: Settings) -> ModelProfile` — Deriva o `ModelProfile` (modelo, limites de contexto e geração) da configuração do run e das configurações globais. Entrada: configuração do run e settings; saída: `ModelProfile`.
- `_select_provider(settings: Settings, run_config: dict) -> LLMProvider` — Escolhe o provider LLM a partir do nome configurado (`ollama`, `llamacpp` ou `mock`), aplicando timeout e mapa de palavras-chave do mock. Entrada: settings e configuração do run; saída: instância de `LLMProvider`.

- `_widen_output_budget(self, task, *, factor) → int` — Aumenta o orçamento de resposta da etapa (o modelo gastou tudo e devolveu nada).
- `_sync_agent_execution(self, task, run_id) → None` — Alinha o estado do agente lógico com o estado da tarefa.

- `RunOrchestrator._widen_output_budget(self, task, *, factor) → int` — Aumenta o orçamento de resposta da etapa (o modelo gastou tudo e devolveu nada).
- `RunOrchestrator._sync_agent_execution(self, task, run_id) → None` — Alinha o estado do agente lógico com o estado da tarefa.
### `src/agent/orchestrator/execution/README.md`

**Propósito:** Índice da pasta `execution/` — como uma etapa roda (despacho, operação de modelo, escrita e verificação). **Quando/onde:** leitura inicial de quem mexe na execução de tarefa.

### `src/agent/orchestrator/execution/__init__.py`

**Propósito:** Fachada do pacote `execution` — reexporta o executor, o runtime e os utilitários usados pelo orquestrador. **Quando/onde:** importado pelo `runner.py`.

### `src/agent/orchestrator/execution/runtime.py`

**Propósito:** Agrupa os colaboradores de uma execução (sessão, configuração, serviço de tarefas, registro de tentativas, registro de ferramentas e fábrica de provedor). **Quando/onde:** criado pelo `RunOrchestrator` e compartilhado com o executor e o modelo.

- `ExecutionRuntime` — Dataclass com os colaboradores da execução; a instância é compartilhada (não copiada) para haver um único registro de ferramentas e uma única contagem de tentativas por run.
- `ExecutionRuntime.build(session, settings=None, *, tasks=None, attempts=None, tools=None, provider_factory=None) -> ExecutionRuntime` — Cria o conjunto de colaboradores; o que não for informado é construído com os padrões (`Settings`, `TaskService`, `AttemptService`, registro de ferramentas).

### `src/agent/orchestrator/execution/executor.py`

**Propósito:** Executa uma única tarefa da árvore e registra o desfecho (despacho por natureza da etapa, verificação e evidência). **Quando/onde:** chamado pelo `RunOrchestrator._step_body` quando a etapa entra em `RUNNING`.

- `TaskExecutor` — Executor de uma etapa; usa a mesma sessão, o mesmo registro de tentativas e o mesmo registro de ferramentas do orquestrador. **Observações:** a verificação é sempre independente de quem executou.
- `TaskExecutor.execute(run, project, task, config, work_root_path=None) -> dict[str, Any]` — Executa a etapa conforme o metadado: ferramenta MCP, resposta final, operação do modelo (com montagem de contexto, streaming e escrita/edição de arquivo) ou ferramenta determinística, com registro de tentativas e tratamento de falhas/loops. Entrada: run, projeto, tarefa, configuração e raiz de trabalho; saída: dicionário de ação (sucesso, falha ou bloqueio).
- `TaskExecutor.finalize_verification(run, project, task, work_root_path=None, implicit_spec=None) -> dict[str, Any]` — Roda a verificação proporcional ao risco (a declarada, ou a implícita de escrita), grava a evidência com snapshot dos artefatos e decide entre concluir, bloquear, planejar recuperação ou reentrar em retry. Entrada: run, projeto, tarefa, raiz de trabalho e spec implícita opcional; saída: dicionário de ação com a evidência/falha.
- `TaskExecutor.write_final_answer(run, project, task, config) -> dict[str, Any]` — Pede ao modelo a resposta final ao usuário (ou a compõe a partir das etapas), extrai as fontes, grava o Markdown e conclui a tarefa, consolidando o pai. Entrada: run, projeto, tarefa e configuração; saída: dicionário de ação `final_answer`.
- `TaskExecutor.plan_verification_recovery(task, vresult, detail, spec) -> dict[str, Any]` — Diagnostica a reprovação da verificação e planeja a recuperação (diagnóstico → correção → re-verificação), contando as recuperações e emitindo `verification.recovery_planned`. Entrada: tarefa, resultado da verificação, detalhe e spec; saída: dicionário de plano de recuperação.
- `TaskExecutor.criteria_of(task) -> dict[str, Any]` — Monta o critério avaliado pela verificação: requisitos cobertos pela etapa (e os parciais) e o critério de aceite dela. Entrada: modelo da tarefa; saída: dicionário com `requirements`, `partial` e `acceptance`.
- `TaskExecutor.save_requested_memory(project, task, args) -> dict` — Executa o pedido de salvar memória feito pelo modelo, definindo escopo (projeto ou conversa) e tipo canônico/contextual. Entrada: projeto, tarefa e argumentos da ferramenta; saída: dicionário com sucesso, id e resumo da memória.
- `TaskExecutor.note_thought(run, task, text, *, phase='thinking', category=None) -> None` — Registra o que está acontecendo como `agent.thought` e publica a frase no feed. Entrada: run, tarefa opcional, texto, fase e categoria; saída: `None`.
- `TaskExecutor.remember_failure(task, failure) -> dict[str, Any]` — Guarda a falha na tarefa (histórico `failures` e `last_failure`) com a assinatura do erro e da estratégia, para a próxima tentativa e o replanejamento lerem. Entrada: tarefa e `Failure`; saída: dicionário da falha registrada.
- `TaskExecutor.work_root(project, task) -> str` — Calcula a raiz de trabalho efetiva do projeto, considerando a conversa da tarefa. Entrada: projeto e tarefa opcional; saída: caminho da raiz de trabalho.
- `TaskExecutor._provider(settings, config)` — Provedor do run segundo a política da execução (a fábrica injetada ou a padrão do pacote).

- `_session(self)` — Sessão SQLAlchemy em uso.
- `_settings(self)` — Configuração do processo.
- `_tasks(self)` — Serviço de tarefas (transições de estado e dependências).
- `_attempts(self)` — Registro de tentativas (contagem, dedup e fingerprint).
- `_tools(self)` — Registro de ferramentas determinísticas.

- `TaskExecutor._session(self)` — Sessão SQLAlchemy em uso.
- `TaskExecutor._settings(self)` — Configuração do processo.
- `TaskExecutor._tasks(self)` — Serviço de tarefas (transições de estado e dependências).
- `TaskExecutor._attempts(self)` — Registro de tentativas (contagem, dedup e fingerprint).
- `TaskExecutor._tools(self)` — Registro de ferramentas determinísticas.

- `TaskExecutor.__init__(self, runtime) → None` — Guarda os colaboradores da execução.
### `src/agent/orchestrator/execution/model_operation.py`

**Propósito:** Executa a etapa de operação de modelo (contexto, ciclo de ferramentas, protocolo JSON da alteração e recusa de escrita). **Quando/onde:** chamado por `TaskExecutor.execute` quando a etapa é `model_operation`.

- `ModelOperation` — Fluxo da operação de modelo; usa os colaboradores do executor que a criou. **Observações:** nada aqui aprova o próprio resultado — a escrita concluída segue para a verificação.
- `ModelOperation.run(run, project, task, config, root_path, ctx) -> dict[str, Any]` — Monta o contexto da operação, chama o modelo (com ciclo de ferramentas quando o provedor suporta), aplica a alteração respondendo ao pedido e devolve o desfecho da etapa. Entrada: run, projeto, tarefa, configuração, pasta de trabalho e contexto de ferramentas; saída: dicionário de ação.
- `ModelOperation._context_overflow(run, project, task, provider_name, profile, exc) -> dict[str, Any]` — Trata o estouro de orçamento de contexto: explica qual componente obrigatório não cabe, registra a tentativa, bloqueia a tarefa e devolve `blocked_context`. Entrada: run, projeto, tarefa, provider, perfil e a exceção; saída: dicionário de ação com a falha.

- `_runtime(self)` — Colaboradores da execução (sessão, settings, serviços, ferramentas).
- `_chat_model(provider_obj, request, *, purpose, stream)` — Chamada ao modelo dentro do ciclo: registra a evidência de cada iteração.
- `_on_tool_call(entry, result) → None` — Registra a chamada de ferramenta feita pelo modelo durante o ciclo.

- `ModelOperation._runtime(self)` — Colaboradores da execução (sessão, settings, serviços, ferramentas).

- `ModelOperation.__init__(self, executor) → None` — Guarda o executor responsável pela etapa.
### `src/agent/orchestrator/execution/providers.py`

**Propósito:** Escolha do provedor do run, perfil do modelo e contabilidade de tokens. **Quando/onde:** usado pelo executor e pelo modelo.

- `select_provider(settings, run_config) -> LLMProvider` — Escolhe o provider LLM a partir do nome configurado (`ollama`, `llamacpp` ou `mock`), aplicando timeout e mapa de palavras-chave do mock. Entrada: settings e configuração do run; saída: instância de `LLMProvider`. **Levanta:** `ProviderConfigError` quando o nome é desconhecido e não há fallback autorizado.
- `default_provider_name(settings) -> str` — Provedor padrão: o do arquivo de provedores, se houver; senão o das settings.
- `profile_from_config(run_config, settings, provider=None) -> ModelProfile` — Deriva o `ModelProfile` (modelo, limites de contexto e geração) da configuração do run e das configurações globais. Entrada: configuração do run e settings; saída: `ModelProfile`.
- `supports_tool_loop(provider) -> bool` — Indica se o provedor sabe manter a conversa de ferramentas (capacidade declarada).
- `apply_provider_usage(task, provider) -> None` — Acumula no metadado da tarefa o uso de tokens reportado pelo provider na última chamada. Entrada: tarefa e provider; saída: `None` (metadado atualizado).

### `src/agent/orchestrator/execution/guards.py`

**Propósito:** Decide o que a etapa pode fazer com as ferramentas e com a resposta do modelo (permissões de escrita e usabilidade do payload). **Quando/onde:** antes de toda escrita e antes de aceitar o JSON do modelo.

- `operation_tools_for(meta: dict, *, registry: Any=None, settings: Any=None, objective: str='') -> tuple[str, ...]` — Ferramentas liberadas para a etapa: núcleo sem escrita quando o pedido é somente leitura, mais as famílias extras pedidas pelo objetivo.
- `write_refusal_reason(meta, tool_name, path) -> str | None` — Motivo da recusa da escrita (somente leitura ou régua de testes protegida) ou `None` quando a escrita é permitida.
- `payload_is_usable(content) -> bool` — Indica se a resposta do modelo já é o JSON que a etapa espera (criar ou editar).
- `evidence_state(passed, blocked=False) -> str` — Traduz o resultado da verificação no estado gravado na evidência: `aprovado`, `reprovado`, `inconclusivo` ou `bloqueado`. Entrada: resultado e flag de bloqueio; saída: string de estado.
- `compact_inspection(inspections, max_items=6, max_chars=900) -> list[dict]` — Encurta a inspeção da tentativa (o que foi lido e um trecho do conteúdo) para o metadado da tarefa.

### `src/agent/orchestrator/execution/tool_results.py`

**Propósito:** Interpreta o resultado de uma ferramenta determinística (distinguir ferramenta quebrada de veredito negativo). **Quando/onde:** após cada execução de ferramenta.

- `is_informative_test_result(tool_id, out) -> bool` — Indica que a suíte rodou e reprovou (resultado, não falha de ferramenta).
- `test_summary(out) -> str` — Resumo curto do que a suíte contou (última linha da saída ou código de saída).
- `as_dict(value) -> dict` — Normaliza o resultado de uma ferramenta em dicionário.

### `src/agent/orchestrator/execution/writes.py`

**Propósito:** Traduz a resposta do modelo em escrita de arquivo, em critério de verificação e em resultado de recusa. **Quando/onde:** no fim da operação de modelo.

- `write_tool_from_payload(data) -> tuple[str, dict[str, Any]]` — Decide entre `edit_file` (há trecho a substituir) e `write_file` (conteúdo inteiro) e devolve os argumentos.
- `implicit_spec(path, written) -> dict[str, Any] | None` — Critério implícito de verificação de uma escrita (`file_contains` com o que foi gravado, com checagem de sintaxe).
- `model_refusal_result(tool_name, path, reason, *, report, snapshot_id=None) -> dict[str, Any]` — Resultado consolidado de uma escrita recusada vinda do modelo.
- `tool_refusal_result(tool_id, path, reason) -> dict[str, Any]` — Resultado consolidado de uma escrita recusada vinda do plano da etapa.

### `src/agent/orchestrator/execution/journal.py`

**Propósito:** Registra no banco o que a execução está fazendo e o que ela já falhou. **Quando/onde:** a cada passo da execução.

- `note_thought(session, run, task, text, *, phase='thinking', category=None) -> None` — Registra `agent.thought` e, em seguida, publica `work.explained`. A falha da publicação não desfaz o registro.
- `_publish_explanation(task: TaskModel | None, text: str, *, phase: str, category: str | None) -> None` — Emite `work.explained` com a categoria da fase quando o chamador não informa outra. Se o evento falhar, a execução segue.
- `remember_failure(task, failure) -> dict[str, Any]` — Guarda a falha na tarefa com assinatura e estratégia (usadas para detectar estagnação).
- `_switch_operational_language(task: TaskModel, cause: str) -> None` — Se a saída inválida veio do inglês operacional, a próxima tentativa usa o pedido original. Não alterna de volta.
- `failure_timestamp() -> str` — Instante atual em ISO-8601 (UTC) para registros de diagnóstico.

### `src/agent/orchestrator/execution/workspace.py`

**Propósito:** Descobre a pasta de trabalho efetiva de uma etapa (projeto ou conversa). **Quando/onde:** antes de executar as ferramentas.

- `work_root(session, project, task) -> str` — Resolve a raiz de trabalho; quando a etapa tem conversa própria, a conversa define a raiz.

### `src/agent/orchestrator/stagnation.py`

**Propósito:** detecta repetição por assinatura normalizada de erro, diagnostica a causa provável e controla os limites operacionais do run. **Quando/onde:** usado pelo `RunOrchestrator` para checar estagnação e, no início de cada passo, para pausar o run quando um limite é atingido.

- `_digest(data: Any) -> str` — Calcula o hash estável (sha1, 16 caracteres) de qualquer estrutura serializável, usado para comparar assinaturas. Entrada: dado qualquer; saída: string hexadecimal.
- `_naive(value: datetime | None) -> datetime | None` — Normaliza um datetime para UTC sem timezone (ou devolve `None`). Entrada: datetime possivelmente nulo; saída: datetime naive ou `None`.
- `diagnose(failure: dict[str, Any], count: int) -> dict[str, Any]` — kind, probable_cause, action, automatic.
- `effective_cap(limits: dict[str, int], key: str, resumes: int, allowance: int=1) -> int` — Cota efetiva de um limite, dada a quantidade de retomadas do run: cada retomada concede uma unidade do limite base, mas o consumo já feito continua contando. Entrada: limites, retomadas, Allowance; saída: cota efetiva (0 quando o limite está desligado).
- `error_signature(failure: dict[str, Any]) -> str` — categoria+causa+texto normalizado (sem números/ids/hashes).
- `limit_reached(session: Session, run: ExecutionRunModel, limits: dict[str, int], *, allowance: int=1) -> dict[str, Any] | None` — verifica limites operacionais.
- `limits_for(settings: Settings, config: dict[str, Any]) -> dict[str, int]` — merge settings + config.limits.
- `next_action_for_limit(run_id: uuid.UUID, hit: dict[str, Any]) -> str` — próxima ação baseada no limite.
- `normalize_error(text: str) -> str` — Normaliza o texto de erro removendo o que muda entre tentativas idênticas (uuids, hex, números, aspas e espaços). Entrada: texto do erro; saída: string normalizada de até 300 caracteres.
- `objective_signature(task: Any) -> str` — Impressão do objetivo da etapa, sem as variações de escrita do mesmo pedido. Entrada: etapa; saída: string hexadecimal (vazia sem objetivo).
- `problem_attempts(root: Any, failure: dict[str, Any], *, workspace: str | None=None, change: bool=False, approach: str='') -> tuple[int, int, dict[str, Any]]` — Conta as tentativas do mesmo problema no objetivo inteiro, morando na raiz (sobrevive ao replanejamento e à retomada). Devolve o trio (tentativas da mesma abordagem, tentativas totais do problema, registro). Uma tentativa só continua a contagem de loop quando nada mudou de material: a mesma operação, a mesma abordagem e o mesmo estado do disco.
- `problem_key(objective: str, signature: str) -> str` — Identidade do problema: o mesmo erro, no mesmo objetivo. É a chave que amarra as tentativas entre si mesmo quando o replanejamento cria etapas novas.
- `repeated_failures(failures: list[dict[str, Any]]) -> int` — conta falhas com mesma signature+strategy.
- `resume_count(session: Session, run: ExecutionRunModel) -> int` — Quantas vezes o run foi retomado. Entrada: sessão e run; saída: contagem dos eventos `run.resumed`.
- `segment_start(session: Session, run: ExecutionRunModel) -> datetime` — Devolve o início do trecho atual do run: o último evento `run.resumed` ou a criação do run, para que retomar não zere o trabalho feito. Entrada: sessão e run; saída: datetime naive.
- `strategy_signature(task: Any) -> str` — tool/args/verification/mode/strategy. Não inclui o objetivo: reescrever o mesmo objetivo não é outra abordagem, e incluí-lo fazia cada replanejamento parecer uma novidade e zerar o contador.
- `usage_since(session: Session, run: ExecutionRunModel) -> dict[str, int]` — Mede o consumo do run: passos sem progresso (no trecho atual), segundos, chamadas ao modelo, chamadas a ferramentas, tokens estimados e replanejamentos. Entrada: sessão e run; saída: dicionário de contadores.

### `src/agent/orchestrator/strategy.py`

**Propósito:** formula a camada de abordagem profissional do pedido (domínio, complexidade, especialidades, requisitos e sequência executável). **Quando/onde:** usado pelo `RunOrchestrator` ao planejar a raiz, para gravar `professional_strategy` e orientar a decomposição adaptativa.

- `ProfessionalStrategist` — Planejador que classifica o objetivo por domínio (consulta, QA, bug, refatoração, documentação, engenharia) e devolve uma estratégia executável proporcional, preservando a intenção original. Entrada: objetivo e resumo de contexto em `analyze`; saída: `ProfessionalStrategy`.
- `ProfessionalStrategist.analyze(objective: str, *, context_summary: str='') -> ProfessionalStrategy` — detecta complexidade/domínio, preserva intenção, define especialidades e sequência de execução.
- `ProfessionalStrategy` — estratégia executável (intenção original, complexidade, domínio, especialidade líder, requisitos, riscos, aceitação, sequência).
- `ProfessionalStrategy.as_dict() -> dict[str, Any]` — Serializa a estratégia em dicionário (inclui `complexity_rank` e `needs_atomization`) para gravar nos metadados da tarefa e nos eventos de observabilidade.
- `ProfessionalStrategy.complexity_rank() -> int` — Traduz a complexidade textual em nível numérico (0 = simples, 1 = moderado, 2 = complexo). Entrada: instância da estratégia; saída: inteiro do ranking.
- `ProfessionalStrategy.from_dict(data: dict[str, Any] | None) -> 'ProfessionalStrategy | None'` — Reconstrói a estratégia a partir do dicionário gravado nos metadados da tarefa, ignorando chaves desconhecidas e devolvendo `None` se faltar o pedido original ou a especialidade líder. Entrada: dicionário (ou `None`); saída: `ProfessionalStrategy` ou `None`.
- `ProfessionalStrategy.needs_atomization() -> bool` — Indica se a etapa interna deve ser subdividida recursivamente em diagnóstico → correção → verificação, o que ocorre para tarefas complexas (rank >= 2). Entrada: instância da estratégia; saída: booleano.
- `ProfessionalStrategy.render_summary() -> str` — Renderiza a estratégia como texto estruturado (domínio, complexidade, especialidades, requisitos, riscos e critérios de aceitação) para inspeção e injeção no contexto.

- `is_read_only_request(objective) → bool` — O pedido proíbe explicitamente alterar o projeto?.
- `protects_test_files(objective) → bool` — O pedido manda mexer nos testes? Se não, os testes são protegidos.
- `looks_like_test_file(path) → bool` — O caminho aponta para um arquivo de teste?.

- `_analyze(self, objective, *, context_summary) → ProfessionalStrategy` — Formula a estratégia a partir do texto do pedido.

- `ProfessionalStrategist._analyze(self, objective, *, context_summary) → ProfessionalStrategy` — Formula a estratégia a partir do texto do pedido.
### `src/agent/orchestrator/usage.py`

**Propósito:** Acúmulo de tokens por tarefa.

- `accumulate_usage(metadata: dict | None, prompt: int, completion: int) -> dict` — atualiza `metadata_json.usage`.
- `remember_usage(provider, prompt: int | None, completion: int | None) -> None` — guarda no `provider.last_usage`.

## `src/agent/persistence/`

**Propósito:** SQLAlchemy 2 + SQLite: modelos, engine e fábrica de sessões.

- Arquivo: [README.md](/src/agent/persistence/README.md)
- Arquivo: [__init__.py](/src/agent/persistence/__init__.py)
- Arquivo: [database.py](/src/agent/persistence/database.py)
- Arquivo: [models.py](/src/agent/persistence/models.py)

### `src/agent/persistence/README.md`

**Propósito:** Índice da pasta `persistence/`.

### `src/agent/persistence/__init__.py`

**Propósito:** Re-exporta `models` + `database`.

### `src/agent/persistence/database.py`

**Propósito:** cria a engine SQLAlchemy, aplica migrações leves de schema no SQLite e oferece um gerenciador de sessão transacional. **Quando/onde:** usado na inicialização do banco e por todos os serviços que precisam de uma `Session` curta.

- `_add_column(conn, table: str, column: str, ddl: str) -> None` — insere uma coluna nova na tabela SQLite se ela ainda não existir, lendo `PRAGMA table_info` antes. Entrada: conexão, nome da tabela/coluna e o DDL do tipo; saída: `None` (efeito colateral no schema).
- `_configure_sqlite(engine: Engine) -> None` — registra um listener de conexão que liga `PRAGMA foreign_keys=ON` quando o backend é SQLite. Entrada: engine; saída: `None`. Quando `create_db_engine` monta a engine.
- `_migrate_sqlite(engine: Engine) -> None` — aplica migrações leves de schema no SQLite: adiciona colunas ausentes (`config_json`, `conversation_id`, `branch_id`, `seq`, `summary`, etc.) e cria o índice `ix_event_logs_run_seq`. Entrada: engine; saída: `None`. Quando `init_db` roda depois do `create_all`.
- `build_session_factory(engine: Engine) -> sessionmaker[Session]` — `expire_on_commit=False`, `future=True`.
- `create_db_engine(settings: Settings | None=None) -> Engine` — `pool_pre_ping=True`, `future=True`.
- `init_db(engine: Engine | None=None, settings: Settings | None=None) -> Engine` — `Base.metadata.create_all`.
- `session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]` — context manager que abre uma sessão, faz `commit` no sucesso, `rollback` em exceção e sempre fecha. Entrada: fábrica de sessões; saída: gerador que entrega a `Session` ativa. Quando os serviços do agente abrem transações curtas.

- `migrate_legacy_schedules(engine) → int` — Converte as linhas antigas de `scheduled_runs` em automações.

- `_set_sqlite_pragma(dbapi_conn, _connection_record) → None` — Aplica um pragma do SQLite na conexão (WAL, chaves estrangeiras, timeout).
### `src/agent/persistence/models.py`

**Propósito:** declara os modelos ORM (SQLAlchemy 2.0) que formam o schema do agente: projetos, conversas, tarefas, runs, memórias, grafo e evidências. **Quando/onde:** importado pelos serviços de persistência e usado por `Base.metadata.create_all` na criação do banco.

- `ProjectRemoteModel` — Computador remoto do projeto: quando existe, as ações do projeto rodam lá por SSH.
- `AutomationModel` — Automação persistente: a definição aprovada de um trabalho que roda sozinho.
- `AutomationFiringModel` — Disparo de uma automação: a unidade de trabalho registrada e recuperável.
- `AutomationEventModel` — Evento durável de automação: a entrada de adaptadores (webhook, arquivo, watcher).
- `AgentModel` — Agente lógico: identidade, papel, instruções, permissões e responsabilidade.
- `AgentExecutionModel` — Execução: instância ativa que usa modelo, contexto e ferramentas.
- `AgentQueryModel` — Consulta de um agente a outro.

- `Base(DeclarativeBase)` — classe base declarativa do SQLAlchemy 2.0 que concentra o metadado de todas as tabelas. Entrada: nenhuma; saída: classe base da qual herdam os modelos. Quando o banco é criado a partir do metadado.
- `BranchModel(Base)` — `branches` (id, conversation_id, parent_id, fork_task_id, created_at).
- `ContextSnapshotModel(Base)` — `context_snapshots` (id, project_id, task_id, run_id, estimated_tokens, components_json, strategy_notes_json, refs_json, created_at).
- `ConversationModel(Base)` — `conversations` (id, project_id, title, locale, root_path, active_branch_id, timestamps).
- `EventLogModel(Base)` — `event_logs` (id, project_id, run_id, task_id, event_type, payload_json, created_at, seq, parent_task_id, agent, schema_version, index `ix_event_logs_run_seq`).
- `EvidenceModel(Base)` — `evidences` (id, task_id, attempt_id, verifier, passed, summary, detail_json, created_at).
- `ExecutionRunModel(Base)` — `execution_runs` (id, project_id, root_task_id, status, config_json, timestamps).
- `KgEdgeModel(Base)` — `kg_edges` (id, project_id, src_id, dst_id, rel, unique `uq_kg_edge`).
- `KgNodeModel(Base)` — `kg_nodes` (id, project_id, kind, ref, label, meta_json, updated_at, unique `uq_kg_node_ref`).
- `MemoryRecordModel(Base)` — `memory_records` (id, project_id, conversation_id, branch_id, task_id, kind, title, content, summary, outline_json, version, source_refs_json, created_at).
- `OperationAttemptModel(Base)` — `operation_attempts` (id, run_id, task_id, kind, provider, request_json, response_json, success, error_message, created_at).
- `ProjectModel(Base)` — `projects` (id, name, root_path, description, path_origin, timestamps).
- `ScheduledRunModel(Base)` — `scheduled_runs` (id, project_id, cron_expression, config_json, enabled, last_run_at, next_run_at, timestamps).
- `TaskContractModel(Base)` — `task_contracts` (id, task_id unique, inputs_json, outputs_json, invariants_json, acceptance_json, created_at).
- `TaskDependencyModel(Base)` — `task_dependencies` (id, task_id, depends_on_task_id, unique pair).
- `TaskModel(Base)` — `tasks` (id, project_id, conversation_id, branch_id, parent_id, title, objective, scope, acceptance_criteria, status, kind, sort_order, metadata_json, consolidated_result_json, timestamps).
- `utcnow() -> datetime` — devolve o instante atual em UTC com fuso, usado como valor padrão das colunas de data/hora. Entrada: nenhuma; saída: `datetime` timezone-aware.

## `src/agent/providers/`

**Propósito:** Provedores de modelo (Ollama, llama.cpp, mock) e o contrato comum.

- Arquivo: [README.md](/src/agent/providers/README.md)
- Arquivo: [__init__.py](/src/agent/providers/__init__.py)
- Arquivo: [base.py](/src/agent/providers/base.py)
- Arquivo: [llamacpp.py](/src/agent/providers/llamacpp.py)
- Arquivo: [mock.py](/src/agent/providers/mock.py)
- Arquivo: [observed.py](/src/agent/providers/observed.py)
- Arquivo: [ollama.py](/src/agent/providers/ollama.py)

- `ProjectRemoteModel` — Computador remoto do projeto: quando existe, as ações do projeto rodam lá por SSH.
- `AutomationModel` — Automação persistente: a definição aprovada de um trabalho que roda sozinho.
- `AutomationFiringModel` — Disparo de uma automação: a unidade de trabalho registrada e recuperável.
- `AutomationEventModel` — Evento durável de automação: a entrada de adaptadores (webhook, arquivo, watcher).
- `AgentModel` — Agente lógico: identidade, papel, instruções, permissões e responsabilidade.
- `AgentExecutionModel` — Execução: instância ativa que usa modelo, contexto e ferramentas.
- `AgentQueryModel` — Consulta de um agente a outro.
### `src/agent/providers/README.md`

**Propósito:** Índice da pasta `providers/`.

### `src/agent/providers/__init__.py`

**Propósito:** Re-exporta `base`, `ollama`, `llamacpp`, `mock`, `observed`.

### `src/agent/providers/base.py`

**Propósito:** Contrato base `LLMProvider` (ABC).

- `ChatCompletionRequest(BaseModel)` — Símbolo do módulo — ver a descrição do arquivo.
- `ChatCompletionResponse(BaseModel)` — Símbolo do módulo — ver a descrição do arquivo.
- `ChatMessage(BaseModel)` — Símbolo do módulo — ver a descrição do arquivo.
- `LLMProvider(ABC)` — Contrato base (ABC) dos provedores de modelo: `name`, `supports_streaming`, `list_models()`, `chat()` e `chat_streaming()` opcional.
- `LLMProvider.chat(request: ChatCompletionRequest) -> ChatCompletionResponse` — Envia a requisição ao modelo e devolve a `ChatCompletionResponse` com o conteúdo e a estimativa de tokens.
- `LLMProvider.chat_streaming(request: ChatCompletionRequest, on_delta: Callable[[str], None]) -> ChatCompletionResponse` — Envia a requisição Emitindo fragmentos via `on_delta`; devolve a resposta completa ao final. Opcional — provedores sem streaming levantam `NotImplementedError`.
- `LLMProvider.list_models() -> list[str]` — Devolve a lista de modelos disponíveis no provider (ids), para a UI e a escolha de perfil.
- `ModelProfile(BaseModel)` — Símbolo do módulo — ver a descrição do arquivo.
- `ProviderError(RuntimeError)` — exceção base.

- `ToolCall` — Chamada de ferramenta pedida pelo modelo. `arguments` é o objeto já decodificado.
- `ProviderCapabilities` — O que o provedor realmente oferece. Recurso ausente é declarado, nunca simulado.
- `ProviderHealth` — Diagnóstico de conectividade de um provedor.
- `ProviderConnectionError` — O servidor não respondeu (recusou a conexão, DNS falhou, host inacessível).
- `ProviderTimeoutError` — A operação estourou o tempo limite configurado.
- `ProviderAuthError` — Credencial ausente, inválida ou sem permissão.
- `ProviderRateLimitError` — Limite de uso do provedor atingido (HTTP 429).
- `ProviderConfigError` — Configuração inválida ou incompleta do provedor (URL, tipo, credencial).
- `ProviderNotSupportedError` — O recurso pedido não existe na API deste provedor.
- `ProviderResponseError` — A resposta chegou, mas não pôde ser lida (JSON inválido, corpo inesperado).
- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor. O padrão assume apenas o que a classe implementa.
- `health_check(self) → ProviderHealth` — Verificação de conectividade barata: lista os modelos do servidor, sem inferência.
- `close(self) → None` — Libera recursos do provedor (nenhum por padrão).

- `_chat(self, request) → ChatCompletionResponse` — Implementação da inferência pelo provedor. Sempre chamada por `chat`.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Implementação do streaming pelo provedor. Sempre chamada por `chat_streaming`.

- `LLMProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor. O padrão assume apenas o que a classe implementa.
- `LLMProvider._chat(self, request) → ChatCompletionResponse` — Implementação da inferência pelo provedor. Sempre chamada por `chat`.
- `LLMProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Implementação do streaming pelo provedor. Sempre chamada por `chat_streaming`.
- `LLMProvider.health_check(self) → ProviderHealth` — Verificação de conectividade barata: lista os modelos do servidor, sem inferência.
- `LLMProvider.close(self) → None` — Libera recursos do provedor (nenhum por padrão).
### `src/agent/providers/llamacpp.py`

**Propósito:** integra servidores llama.cpp/llama-server pela API compatível com OpenAI, com chat simples e streaming. **Quando/onde:** usado como provedor de inferência local quando o `provider` configurado é `llamacpp`.

- `LlamaCppProvider(LLMProvider)` — `name="llamacpp"`, `supports_streaming=True`.
- `LlamaCppProvider.__init__(base_url: str, timeout: float=120.0) -> None` — normaliza a URL base (sem barra final) e guarda o timeout das requisições HTTP. Entrada: URL do servidor llama.cpp e timeout; saída: `None`.
- `LlamaCppProvider._body(request: ChatCompletionRequest) -> dict` — monta o corpo JSON compatível com a API OpenAI: modelo do perfil, mensagens convertidas, `max_tokens` da reserva de saída, parâmetros de geração e o `response_format` quando houver. Entrada: requisição de chat; saída: dicionário pronto para o POST.
- `LlamaCppProvider.chat(request: ChatCompletionRequest) -> ChatCompletionResponse` — Faz `POST /v1/chat/completions` no formato compatível com OpenAI e devolve a resposta com `usage.prompt_tokens`/`completion_tokens`.
- `LlamaCppProvider.chat_streaming(request: ChatCompletionRequest, on_delta: Callable[[str], None]) -> ChatCompletionResponse` — Consome o SSE de `POST /v1/chat/completions`, entregando cada delta ao `on_delta` e devolvendo a resposta completa.
- `LlamaCppProvider.list_models() -> list[str]` — Consulta `GET /v1/models` do llama.cpp e devolve os ids dos modelos carregados.
- `_data_url(encoded: str) -> str` — monta a `data:` URL de uma imagem base64, inferindo `image/jpeg` (prefixo `/9j/`) ou `image/png`. Entrada: base64 da imagem; saída: string `data:<mime>;base64,<dados>`.
- `_openai_message(message) -> dict` — converte uma `ChatMessage` no formato OpenAI: texto simples quando não há imagens, ou lista de partes `text` + `image_url` quando há. Entrada: mensagem do request; saída: dicionário `{role, content}`.

- `read_api_key_file(path) → str` — `llama-server --api-key-file` guarda a chave em arquivo; o conteúdo vira o bearer token.
- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.

- `_tool_calls(message) → list[ToolCall] | None` — Extrai as chamadas de ferramenta de uma mensagem do llama-server.
- `_client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — `stream: true` no endpoint OpenAI: eventos `data: {...}` com `choices[0].delta.content` até `[DONE]`;.
- `_chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pelo llama-server.

- `LlamaCppProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `LlamaCppProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `LlamaCppProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — `stream: true` no endpoint OpenAI: eventos `data: {...}` com `choices[0].delta.content` até `[DONE]`;.
- `LlamaCppProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pelo llama-server.
### `src/agent/providers/mock.py`

**Propósito:** provedor de inferência determinístico, sem rede, para testes e simulações. **Quando/onde:** usado nos testes e em execuções sem modelo real, quando o `provider` configurado é `mock`.

- `MockProvider(LLMProvider)` — `name="mock"`, `supports_streaming=False`.
- `MockProvider.__init__(responses: list[str] | None=None, keyword_map: dict[str, str] | None=None) -> None` — prepara o provedor com respostas em sequência, mapa palavra-chave→resposta e contador de chamadas. Entrada: listas/dicionários opcionais; saída: `None`.
- `MockProvider.chat(request: ChatCompletionRequest) -> ChatCompletionResponse` — Procura a primeira palavra-chave do mapa na última mensagem do usuário e devolve a resposta correspondente — permite testes E2E sem modelo real.
- `MockProvider.list_models() -> list[str]` — Devolve as chaves do mapa de palavras-chave configurado — os modelos do provider de teste.
- `decomposition_json(subtasks: list[dict[str, Any]]) -> str` — serializa a lista de subtarefas no JSON `{"subtasks": [...]}` usado como resposta simulada da decomposição. Entrada: lista de specs; saída: string JSON com `ensure_ascii=False`.

- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.

- `_chat(self, request) → ChatCompletionResponse` — Devolve a resposta correspondente ao pedido, de forma determinística.

- `MockProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `MockProvider._chat(self, request) → ChatCompletionResponse` — Devolve a resposta correspondente ao pedido, de forma determinística.
### `src/agent/providers/observed.py`

**Propósito:** Wrapper `observed_chat` — emite eventos streaming no EventBus.

- `observed_chat(provider: LLMProvider, request: ChatCompletionRequest, *, purpose: str, stream: bool=True) -> ChatCompletionResponse` — Chama o provider emitindo os eventos de streaming no barramento (`agent.started`, `agent.output.delta`, `agent.output.completed/failed`) e agrupa os fragmentos; devolve a resposta completa.

- `publish(text) → None` — Publica um fragmento do texto recebido, com o deslocamento acumulado.
- `on_delta(piece) → None` — Acumula um fragmento e agenda sua publicação em lote.
- `failed(error, *, cancelled) → None` — Publica o desfecho de falha, preservando o texto parcial recebido.
### `src/agent/providers/ollama.py`

**Propósito:** integra o Ollama por HTTP (`/api/tags`, `/api/chat`), com chat simples e streaming. **Quando/onde:** usado como provedor de inferência local quando o `provider` configurado é `ollama`.

- `_ollama_tool_call(call) → dict` — Chamada de ferramenta no formato do Ollama (`function.name` + `function.arguments` já decodificado).
- `_tool_calls(message) → list[ToolCall] | None` — Extrai as chamadas de ferramenta de uma mensagem do Ollama.
- `OllamaProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `OllamaProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `OllamaProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API do Ollama.
- `OllamaProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — `/api/chat` com `stream: true`: uma linha JSON por fragmento; a última (`done`) traz uso de tokens.

- `OllamaProvider(LLMProvider)` — `name="ollama"`, `supports_streaming=True`.
- `OllamaProvider.__init__(base_url: str, timeout: float=120.0) -> None` — normaliza a URL base (sem barra final) e guarda o timeout usado nas chamadas HTTP ao Ollama. Entrada: URL do servidor e timeout; saída: `None`.
- `OllamaProvider.chat(request: ChatCompletionRequest) -> ChatCompletionResponse` — Faz `POST /api/chat` com `stream=false` e devolve a resposta, usando `prompt_eval_count`/`eval_count` como tokens.
- `OllamaProvider.chat_streaming(request: ChatCompletionRequest, on_delta: Callable[[str], None]) -> ChatCompletionResponse` — Faz `POST /api/chat` com `stream=true` e percorre as linhas JSON, entregando cada fragmento ao `on_delta` e devolvendo a resposta completa.
- `OllamaProvider.list_models() -> list[str]` — Consulta `GET /api/tags` no Ollama e devolve os ids dos modelos instalados.
- `_ollama_message(message) -> dict` — converte `ChatMessage` + images.
- `_reasoning_model(model_id: str) -> bool` — detecta qwen3, gpt-oss, deepseek, reason.
- `chat_body(request: ChatCompletionRequest) -> dict` — monta body (model, messages, stream, options, format, think para reasoning models).
- `inference_failure_text(exc: Exception) -> str` — normaliza erro (timeout → "tempo esgotado").

## `src/agent/security/`

**Propósito:** Resolução segura de caminhos dentro da pasta do projeto.

- Arquivo: [README.md](/src/agent/security/README.md)
- Arquivo: [paths.py](/src/agent/security/paths.py)

- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.

- `_ollama_tool_call(call) → dict` — Chamada de ferramenta no formato do Ollama (`function.name` + `function.arguments` já decodificado).
- `_tool_calls(message) → list[ToolCall] | None` — Extrai as chamadas de ferramenta de uma mensagem do Ollama.
- `_client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `_chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API do Ollama.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — `/api/chat` com `stream: true`: uma linha JSON por fragmento; a última (`done`) traz uso de tokens.

- `OllamaProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `OllamaProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `OllamaProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API do Ollama.
- `OllamaProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — `/api/chat` com `stream: true`: uma linha JSON por fragmento; a última (`done`) traz uso de tokens.
### `src/agent/security/README.md`

**Propósito:** Índice da pasta `security/`.

### `src/agent/security/paths.py`

**Propósito:** Resolução segura de paths dentro do `project_root`.

- `PathSecurityError(ValueError)` — exceção de path fora do escopo.
- `resolve_under_root(root: str | Path, user_path: str) -> Path` — normaliza, resolve symlinks, verifica `candidate.relative_to(root)`, levanta `PathSecurityError` se fora.

## `src/agent/services/`

**Propósito:** Regras de negócio (projetos, conversas, tarefas, runs, memória, métricas, worker).

- Arquivo: [README.md](/src/agent/services/README.md)
- Arquivo: [__init__.py](/src/agent/services/__init__.py)
- Arquivo: [attachments.py](/src/agent/services/attachments.py)
- Arquivo: [attempt_service.py](/src/agent/services/attempt_service.py)
- Arquivo: [autonomous_worker.py](/src/agent/services/autonomous_worker.py)
- Arquivo: [branches.py](/src/agent/services/branches.py)
- Arquivo: [contract_service.py](/src/agent/services/contract_service.py)
- Arquivo: [conversation_service.py](/src/agent/services/conversation_service.py)
- Arquivo: [fs_browse.py](/src/agent/services/fs_browse.py)
- Arquivo: [inbox.py](/src/agent/services/inbox.py)
- Arquivo: [metrics_service.py](/src/agent/services/metrics_service.py)
- Arquivo: [project_service.py](/src/agent/services/project_service.py)
- Arquivo: [run_service.py](/src/agent/services/run_service.py)
- Arquivo: [scheduler.py](/src/agent/services/scheduler.py)
- Arquivo: [task_service.py](/src/agent/services/task_service.py)

### `src/agent/services/README.md`

**Propósito:** Índice da pasta `services/`.

### `src/agent/services/__init__.py`

**Propósito:** Re-exporta todos os 11 services.

### `src/agent/services/attachments.py`

**Propósito:** Materializa anexos colados no chat (texto, imagem, arquivo) em disco dentro do projeto. **Quando/onde:** chamado ao receber mensagens com anexos, antes de montar o contexto do modelo.

- `_safe_name(name: str, fallback: str) -> str` — Higieniza o nome do arquivo: extrai apenas o basename, troca caracteres fora de `[A-Za-z0-9._-]` por `-`, remove pontuação das pontas e trunca em 80 caracteres; devolve `fallback` quando o nome fica vazio. Quando `materialize_attachments` monta o nome de destino do anexo.
- `attachment_note(refs: list[dict]) -> str` — texto para anexar ao objective.
- `materialize_attachments(project_root: str, task_id: str, items: list) -> list[dict]` — salva arquivos, retorna refs `{path, mime, size}`.

- `_attachments_folder(project_root, task_id) → str` — Pasta de anexos da tarefa. Mantém a pasta legada quando ela já tem arquivos,.
### `src/agent/services/attempt_service.py`

**Propósito:** Registro de tentativas de operação e detecção de loops de saída repetida. **Quando/onde:** usado pelo orquestrador a cada chamada de modelo/ferramenta para persistir o histórico e decidir quando desistir.

- `AttemptService` — Símbolo do módulo — ver a descrição do arquivo.
- `AttemptService.__init__(session: Session, max_attempts: int=8) -> None` — Inicializa o serviço com a sessão de banco e o limite máximo de tentativas por tarefa (8 por padrão). Quando o orquestrador cria o registrador de tentativas.
- `AttemptService.attempts_exhausted(task_id: uuid.UUID) -> bool` — Indica se a tarefa já atingiu o limite de tentativas configurado.
- `AttemptService.count_attempts(task_id: uuid.UUID) -> int` — Conta as tentativas já registradas para a tarefa — base do limite de tentativas.
- `AttemptService.fingerprint(data: dict | str) -> str` — Calcula o fingerprint SHA256 normalizado de um payload (chaves ordenadas, espaços normalizados) para comparar prompts e saídas.
- `AttemptService.prompt_already_sent(task_id: uuid.UUID, prompt_fp: str) -> bool` — Indica se o mesmo prompt (mesmo fingerprint) já foi enviado para a tarefa — evita repetir a mesma chamada.
- `AttemptService.record(*, run_id: uuid.UUID, task_id: uuid.UUID, kind: AttemptKind, provider: str | None, request: dict | None, response: dict | None, success: bool, error: str | None=None, project_id: uuid.UUID | None=None, failure: Failure | None=None) -> OperationAttemptModel` — Grava uma `OperationAttemptModel` (tipo, provider, request, response, sucesso e falha) e devolve a linha persistida.
- `AttemptService.repeated_output_detected(task_id: uuid.UUID, output_fingerprint: str, window: int=3) -> bool` — Indica se a mesma saída (mesmo fingerprint) apareceu na janela recente de tentativas — sinal de loop.

- `count_model_calls(self, task_id) → int` — Chamadas ao modelo da tarefa, incluindo as iterações do ciclo de ferramentas.
- `count_tool_calls(self, task_id) → int` — Chamadas de ferramenta feitas pela tarefa.

- `AttemptService.count_model_calls(self, task_id) → int` — Chamadas ao modelo da tarefa, incluindo as iterações do ciclo de ferramentas.
- `AttemptService.count_tool_calls(self, task_id) → int` — Chamadas de ferramenta feitas pela tarefa.
### `src/agent/services/autonomous_worker.py`

**Propósito:** Execução autônoma em segundo plano, varrendo runs ativos em loop. **Quando/onde:** usado pelo servidor da API para avançar runs marcados como `autonomous` sem intervenção do usuário.

- `autonomous_loop(interval_sec: float=2.0) -> None` — a cada intervalo, `step()` runs `ACTIVE` + `autonomous=true`.
- `enable_autonomous_on_run(session, run_id: uuid.UUID) -> ExecutionRunModel` — seta `config.autonomous=true`.
- `request_stop() -> None` — Seta o evento global `_stop`, sinalizando ao `autonomous_loop` que deve encerrar na próxima iteração. Quando se solicita o desligamento do worker de fundo.
- `start_background_worker() -> asyncio.Task` — inicia loop (lifespan API).
- `stop_background_worker() -> None` — cancela task.

- `build_scheduler(settings) → AgentScheduler` — Escalonador do worker, com os tratadores de etapa de run e de consulta.

- `_run_step(operation) → dict` — Avança um run autônomo e devolve a ação do passo.
- `_answer_query(operation) → dict` — Resolve uma consulta pendente: estado persistido primeiro, inferência se faltar.
### `src/agent/services/branches.py`

**Propósito:** Lógica de visibilidade de branches + memória.

- `_aware(value: datetime | None) -> datetime | None` — normaliza timezone.
- `ancestor_chain(branches: dict[uuid.UUID, BranchModel], branch_id: uuid.UUID | None) -> list[BranchModel]` — cadeia ancestral até raiz.
- `memory_visible(*, memory_branch_id: uuid.UUID | None, memory_created_at: datetime | None, conversation_id: uuid.UUID | None, task_branch_id: uuid.UUID | None, branches: dict[uuid.UUID, BranchModel]) -> bool` — memória visível se branch ancestral ou mesma branch.
- `visible_tasks(tasks: list[TaskModel], branch: BranchModel, branches: dict[uuid.UUID, BranchModel]) -> list[TaskModel]` — filtra tasks visíveis na branch ativa.

- `root_id(task) → uuid.UUID` — Identificador da raiz da conversa à qual a branch pertence.
### `src/agent/services/contract_service.py`

**Propósito:** Contratos explícitos entre tarefas (entradas, saídas, invariantes, aceite) e análise de impacto por arquivos. **Quando/onde:** usado ao planejar decomposição de tarefas e ao localizar tarefas afetadas por mudanças de contrato.

- `ContractService` — Símbolo do módulo — ver a descrição do arquivo.
- `ContractService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy usada para ler e gravar `TaskContractModel`. Quando o serviço é instanciado.
- `ContractService.file_refs_from_contract(row: TaskContractModel) -> list[str]` — Extrai do contrato as referências de arquivos procuradas nas chaves `files`, `paths` e `modules` de `outputs_json`, `inputs_json` e `acceptance_json`; devolve lista de strings (vazia se os blocos não forem dicts). Quando se quer saber quais arquivos um contrato toca.
- `ContractService.find_impacted_tasks(project_id: uuid.UUID, file_refs: list[str]) -> list[uuid.UUID]` — Cruza as referências de arquivo com o texto das tarefas do projeto (objective, título, metadata) e com os nós do grafo de conhecimento (`KgNodeModel`); devolve os ids das tarefas impactadas (vazio se `file_refs` for vazio). Quando se avalia o alcance de uma mudança de contrato.
- `ContractService.get(task_id: uuid.UUID) -> TaskContractModel | None` — Devolve o contrato (`TaskContractModel`) da tarefa ou `None` quando ela ainda não tem contrato.
- `ContractService.upsert(task_id: uuid.UUID, *, inputs: dict | None=None, outputs: dict | None=None, invariants: list | None=None, acceptance: dict | None=None) -> TaskContractModel` — Cria ou atualiza o contrato da tarefa, aplicando apenas os blocos não-None e persistindo com flush; devolve a linha `TaskContractModel`. Levanta `LookupError` se a tarefa não existir.
- `ContractService.upsert_with_impact(task_id: uuid.UUID, *, inputs: dict | None=None, outputs: dict | None=None, invariants: list | None=None, acceptance: dict | None=None) -> dict` — Grava o contrato da tarefa (entradas, saídas, invariantes, aceite) e devolve o impacto: as tarefas afetadas pelos arquivos citados.
- `ContractService.validate_for_run(task_id: uuid.UUID) -> tuple[bool, list[str]]` — Valida o contrato antes de a tarefa executar; devolve `(ok, erros)` — bloqueia a execução quando há entrada exigida ausente.

### `src/agent/services/conversation_service.py`

**Propósito:** Gerencia conversas dentro e fora de projetos, incluindo ramos, movimentação e o projeto "inbox". **Quando/onde:** usado pela API de chat para criar, listar, mover e apagar conversas e suas tarefas.

- `ConversationService` — Símbolo do módulo — ver a descrição do arquivo.
- `ConversationService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy. Quando o serviço é instanciado pela camada de chat.
- `ConversationService._assign(task: TaskModel, conversation_id: uuid.UUID) -> None` — Define `conversation_id` na tarefa e propaga recursivamente aos filhos via `parent_id`. Quando uma árvore de tarefas é vinculada a uma conversa.
- `ConversationService._backfill(project_id: uuid.UUID) -> None` — Cria conversas para tarefas raiz antigas sem `conversation_id`, detectando o idioma pelo `metadata_json` ou por `detect_language`, e as vincula com `_assign`. Quando `list_conversations` precisa exibir tarefas herdadas de versões anteriores.
- `ConversationService._ensure_inbox() -> ProjectModel` — Devolve o projeto "inbox" de conversas soltas, criando-o via `ProjectService.create_project` (nome "Conversas soltas", raiz na home, `origin="inbox"`) caso ainda não exista. Quando é preciso um destino para conversas fora de projeto.
- `ConversationService._find_inbox() -> ProjectModel | None` — Localiza o projeto inbox por `root_path == INBOX_ROOT` ou `path_origin == "inbox"`, normalizando `root_path` para a home do usuário; devolve `None` se não existir. Quando se consulta o inbox sem criá-lo.
- `ConversationService.activate_branch(conversation_id: uuid.UUID, branch_id: uuid.UUID) -> ConversationModel` — Ativa um ramo da conversa — a partir daí as novas mensagens entram nele.
- `ConversationService.branches_of(conversation_id: uuid.UUID) -> list[BranchModel]` — Devolve todos os ramos da conversa, do mais antigo ao mais recente.
- `ConversationService.create_conversation(project_id: uuid.UUID, data: ConversationCreate) -> ConversationModel` — Cria uma conversa dentro de um projeto, herdando a raiz de trabalho do projeto.
- `ConversationService.create_loose(data: ConversationCreate) -> ConversationModel` — Cria uma conversa sem projeto (inbox), usando a pasta do usuário como raiz de trabalho.
- `ConversationService.delete_conversation(conversation_id: uuid.UUID) -> None` — Apaga a conversa e as tarefas que pertencem a ela.
- `ConversationService.ensure_branch(conversation: ConversationModel) -> BranchModel` — Garante que a conversa tenha uma branch ativa; cria a primeira branch quando necessário.
- `ConversationService.fork_message(conversation_id: uuid.UUID, task_id: uuid.UUID, objective: str) -> TaskModel` — Cria um ramo (branch) a partir de uma tarefa e uma task-raiz com o objetivo do fork, permitindo refazer a conversa a partir de uma mensagem.
- `ConversationService.get_conversation(conversation_id: uuid.UUID) -> ConversationModel` — Devolve a conversa pelo id; levanta `LookupError` se não existir.
- `ConversationService.list_conversations(project_id: uuid.UUID) -> list[ConversationModel]` — Devolve as conversas de um projeto, da mais recente para a mais antiga.
- `ConversationService.list_loose() -> list[ConversationModel]` — Devolve as conversas sem projeto (inbox).
- `ConversationService.move_conversation(conversation_id: uuid.UUID, project_id: uuid.UUID | None) -> ConversationModel` — Move a conversa para outro projeto ou de volta para o inbox, ajustando suas tarefas.
- `ConversationService.rename(conversation_id: uuid.UUID, title: str) -> ConversationModel` — Renomeia a conversa e grava o título exibido na UI.
- `ConversationService.set_root(conversation_id: uuid.UUID, root_path: str | None) -> ConversationModel` — Define (ou limpa) a pasta de trabalho da conversa — permite trabalhar fora da pasta do projeto.
- `ConversationService.tasks_for_branch(conversation_id: uuid.UUID, branch_id: uuid.UUID | None=None) -> list[TaskModel]` — Devolve as tarefas visíveis na branch informada (inclui as ancestrais).
- `ConversationService.touch_title(conversation_id: uuid.UUID, title: str, locale: str) -> None` — Atualiza título e idioma (locale) da conversa a partir do texto do usuário.
- `locale_for_task(session: Session, task: TaskModel | None) -> str` — Sobe a árvore de tarefas até a raiz para descobrir a conversa e usar seu `locale`; senão usa `metadata_json["locale"]` ou `detect_language` do objective/título; devolve "pt" quando não há tarefa. Quando se decide o idioma de resposta de uma tarefa.

### `src/agent/services/fs_browse.py`

**Propósito:** Escolha e navegação de pastas do projeto restritas a raízes permitidas. **Quando/onde:** usado pela API de seleção de diretório e pelo seletor nativo de pasta no macOS.

- `_allowed(path: Path) -> bool` — Resolve o caminho e verifica se ele é igual a alguma raiz permitida ou está dentro dela; devolve `True`/`False`. Quando `browse_directories` e `pick_folder_native` filtram pastas fora do alcance.
- `_roots() -> list[Path]` — Monta a lista de raízes permitidas: a home do usuário mais `/Users`, `/Volumes` e `/home`, quando existirem. Quando `_allowed` precisa delimitar o alcance da navegação.
- `browse_directories(path: str | None=None) -> dict` — lista entradas (path, kind=dir/file), `os.listdir`.
- `pick_folder_native() -> str` — macOS `osascript` para escolher pasta no Finder.

- `create_directory(path, name) → dict` — Cria uma pasta dentro de `path` (que precisa estar no alcance permitido).
### `src/agent/services/inbox.py`

**Propósito:** Representa a pasta do usuário como destino padrão quando nenhum diretório foi escolhido. **Quando/onde:** usado por `ConversationService` e `ProjectService` para criar e reconhecer o projeto de conversas soltas.

- `effective_root(project, conversation=None) -> str` — `conversation.root_path` ou `project.root_path` ou `Path.home()`.
- `is_inbox_path(root_path: str | None) -> bool` — Indica se o caminho começa com o prefixo `agente-inbox://`; devolve `True`/`False` (string vazia ou None resultam em False). Quando se distingue caminhos de inbox de pastas reais.
- `is_inbox_project(project) -> bool` — `project.path_origin != "chosen"`.
- `user_home() -> str` — Devolve a home do usuário como string (`Path.home()`), usada como raiz efetiva quando não há pasta escolhida. Quando se resolve a raiz de um projeto sem `root_path` explícito.

### `src/agent/services/metrics_service.py`

**Propósito:** Métricas agregadas de execução por projeto e por run, com detecção de estagnação e evidências. **Quando/onde:** usado pela API de observabilidade e pelo painel de progresso de um run.

- `MetricsService` — Símbolo do módulo — ver a descrição do arquivo.
- `MetricsService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy usada nas agregações. Quando o serviço é instanciado.
- `MetricsService._max_depth(tasks: list[TaskModel]) -> int` — Percorre a cadeia `parent_id` de cada tarefa dentro do conjunto e devolve a maior profundidade da árvore (0 se não houver hierarquia). Quando se calcula a profundidade da árvore de tarefas.
- `MetricsService._model_calls_since_progress(attempts: list, events: list) -> int` — Encontra o último evento `orchestrator.action` que representa avanço (`made_progress`) e conta as tentativas de tipo `model` criadas depois dele; devolve o contador. Quando se mede o quanto o run avançou desde a última evolução verificável.
- `MetricsService.project_metrics(project_id: uuid.UUID) -> dict` — Devolve as métricas agregadas do projeto: tasks por status, tokens totais, tentativas e evidências.
- `MetricsService.run_metrics(run_id: uuid.UUID) -> dict | None` — Devolve as métricas de uma execução: passos, tentativas, tokens, duração e progresso real (verificados/pendentes).
- `_current(evidence: EvidenceModel) -> bool` — Indica se a evidência ainda reflete o estado atual dos artefatos, delegando a `verification.fingerprint.is_current` com os artefatos de `detail_json`; devolve booleano. Quando se separa evidências válidas de evidências obsoletas.
- `_naive(moment)` — Normaliza um `datetime` removendo o fuso (`replace(tzinfo=None)`), pois SQLite devolve datas ingênuas e as em memória estão em UTC; devolve `None` se a entrada for None. Quando se comparam timestamps vindos do banco com timestamps em memória.

### `src/agent/services/project_service.py`

**Propósito:** CRUD de projetos e memória canônica inicial, com saneamento de pastas vazadas por testes. **Quando/onde:** usado pela API para criar e listar projetos e registrar memórias do projeto.

- `ProjectService` — Símbolo do módulo — ver a descrição do arquivo.
- `ProjectService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy. Quando o serviço é instanciado.
- `ProjectService.add_memory(project_id: uuid.UUID, data: MemoryCreate) -> MemoryRecordModel` — Grava um fato na memória do projeto ou da conversa e devolve o registro criado.
- `ProjectService.create_project(data: ProjectCreate, *, origin: str | None=None) -> ProjectModel` — Cria um projeto (nome, pasta raiz, descrição) e devolve a linha persistida.
- `ProjectService.get_project(project_id: uuid.UUID) -> ProjectModel` — Devolve o projeto pelo id; levanta `LookupError` se não existir.
- `ProjectService.list_memory(project_id: uuid.UUID, kind: MemoryKind | None=None) -> list[MemoryRecordModel]` — Devolve as memórias do projeto, opcionalmente filtrando por `kind`.
- `ProjectService.list_projects() -> list[ProjectModel]` — Devolve todos os projetos cadastrados, da criação mais recente para a mais antiga.
- `ProjectService.update_project(project_id: uuid.UUID, *, name: str | None=None, root_path: str | None=None) -> ProjectModel` — Atualiza nome, pasta raiz e/ou descrição do projeto e devolve a linha persistida.
- `_is_leaked_test_project(root_path: str) -> bool` — Detecta caminhos residuais de `pytest-of-`/`/T/pytest-` ou o pseudo-caminho de inbox; devolve `True` para descartar esses projetos. Quando `list_projects` filtra projetos que escaparam de testes automatizados.

- `get_remote(self, project_id) → dict | None` — Configuração do computador remoto do projeto (None quando o projeto é local).
- `set_remote(self, project_id, config) → dict` — Grava a configuração do computador remoto do projeto.
- `clear_remote(self, project_id) → bool` — Remove a configuração do computador remoto do projeto.
- `delete_project(self, project_id) → dict` — Remove o projeto e tudo que pertence a ele: conversas, tarefas, execuções, eventos,.

- `ProjectService.get_remote(self, project_id) → dict | None` — Configuração do computador remoto do projeto (None quando o projeto é local).
- `ProjectService.set_remote(self, project_id, config) → dict` — Grava a configuração do computador remoto do projeto.
- `ProjectService.clear_remote(self, project_id) → bool` — Remove a configuração do computador remoto do projeto.
- `ProjectService.delete_project(self, project_id) → dict` — Remove o projeto e tudo que pertence a ele: conversas, tarefas, execuções, eventos,.
### `src/agent/services/run_service.py`

**Propósito:** Controle do ciclo de vida de execuções (start, pause, resume, cancel) e registro de eventos. **Quando/onde:** usado pela API de execução e pelo orquestrador ao retomar ou cancelar runs.

- `RunService` — Símbolo do módulo — ver a descrição do arquivo.
- `RunService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy. Quando o serviço é instanciado.
- `RunService._under(task: TaskModel, root_id: uuid.UUID) -> bool` — Sobe a cadeia de `parent_id` da tarefa (com proteção contra ciclos via `seen`) verificando se ela é descendente da tarefa raiz; devolve `True`/`False`. Quando `resume_run` decide quais tarefas bloqueadas devem voltar para PLANNING.
- `RunService.cancel_run(run_id: uuid.UUID) -> ExecutionRunModel` — Cancela a execução (ACTIVE/PAUSED → CANCELLED) e devolve a run atualizada.
- `RunService.list_runs(project_id: uuid.UUID) -> list[ExecutionRunModel]` — Devolve as execuções de um projeto, da mais recente para a mais antiga.
- `RunService.pause_run(run_id: uuid.UUID) -> ExecutionRunModel` — Símbolo do módulo — ver a descrição do arquivo.
- `RunService.resume_run(run_id: uuid.UUID, *, retry_blocked: bool=False) -> ExecutionRunModel` — Retoma uma execução pausada (PAUSED → ACTIVE); com `retry_blocked`, move tarefas BLOCKED de volta para PLANNING e zera os contadores de limites.
- `RunService.start_run(project_id: uuid.UUID, data: ExecutionRunCreate) -> ExecutionRunModel` — Símbolo do módulo — ver a descrição do arquivo.

- `RunService._usage(run: ExecutionRunModel) -> dict[str, int]` — Consumo acumulado do run, para a auditoria da retomada: a retomada concede cota nova, mas o que já foi gasto continua contando. Entrada: run; saída: consumo por indicador.
### `src/agent/services/scheduler.py`

**Propósito:** Serviço de agendamento cron que dispara execuções automáticas. **Quando/onde:** usado pelo servidor da API quando há `ScheduledRunModel` habilitados.

- `_get_next_run_time(cron_expr: str, base_time: datetime | None=None) -> datetime` — Calcula o próximo horário a partir da expressão cron usando `croniter`, com base em `base_time` ou em `datetime.now()`; devolve o datetime resultante. Quando se agenda ou reagenda um schedule.
- `_schedule_job(schedule_id: str) -> None` — Callback do APScheduler: carrega o schedule, ignora se ausente ou desabilitado, cria um `ExecutionRunModel` ACTIVE com o `config_json` do schedule e atualiza `last_run_at`/`next_run_at`; erros são logged e a transação revertida. Quando o cron dispara uma execução agendada.
- `schedule_disabled_on_run(session, schedule_id: str) -> ScheduledRunModel` — Marca o schedule como desabilitado (`enabled = False`) e devolve a linha; levanta `LookupError` se o id não existir. Quando se pausa um agendamento.
- `schedule_enabled_on_run(session, schedule_id: str) -> ScheduledRunModel` — Marca o schedule como habilitado (`enabled = True`) e devolve a linha; levanta `LookupError` se o id não existir. Quando se reativa um agendamento.
- `start_scheduler() -> None` — inicia scheduler, agenda jobs ativos.
- `stop_scheduler() -> None` — para scheduler.

- `current_supervisor() → AutomationSupervisor | None` — Supervisor de automações em execução.
- `legacy_scheduled_run(session, schedule_id) → ScheduledRunModel | None` — Linha antiga de `scheduled_runs` (compatibilidade de leitura).

- `_as_uuid(schedule_id) → uuid.UUID` — Normaliza um identificador de agendamento para `uuid.UUID`.
### `src/agent/services/task_service.py`

**Propósito:** CRUD de tarefas, dependências e transições de status com log de eventos. **Quando/onde:** usado pela API e pelo orquestrador para criar, consultar e promover tarefas dentro de um projeto.

- `DependencyError(ValueError)` — Exceção de domínio sinalizando dependência inválida (projeto diferente, auto-dependência ou ciclo). Quando `add_dependency` recusa a criação do vínculo.
- `TaskNotFoundError(LookupError)` — Exceção de domínio para tarefa inexistente ou pertencente a outro projeto. Quando `get_task`/`create_task` não encontram a referência pedida.
- `TaskService` — CRUD de tarefas, dependências (com validação de DAG) e transições de status auditadas na máquina de estados.
- `TaskService.__init__(session: Session) -> None` — Inicializa o serviço guardando a sessão SQLAlchemy usada para ler e gravar tarefas, dependências e eventos. Quando o serviço é instanciado pela camada de API ou pelo orquestrador.
- `TaskService._creates_cycle(task_id: uuid.UUID, new_dep: uuid.UUID) -> bool` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService._log_event(*, project_id: uuid.UUID, task_id: uuid.UUID | None, event_type: str, payload: dict | None, run_id: uuid.UUID | None=None) -> None` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.add_dependency(task_id: uuid.UUID, data: TaskDependencyCreate) -> TaskDependencyModel` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.create_task(project_id: uuid.UUID, data: TaskCreate) -> TaskModel` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.dependencies_satisfied(task_id: uuid.UUID) -> bool` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.get_task(task_id: uuid.UUID) -> TaskModel` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.list_tasks(project_id: uuid.UUID) -> list[TaskModel]` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.promote_ready_if_dependencies_met(task_id: uuid.UUID) -> TaskModel | None` — Símbolo do módulo — ver a descrição do arquivo.
- `TaskService.update_status(task_id: uuid.UUID, update: TaskStatusUpdate) -> TaskModel` — Símbolo do módulo — ver a descrição do arquivo.

## `src/agent/skills/`

**Propósito:** Skills do agente: contrato, catálogo, descoberta, seleção e injeção no prompt.

- Subpasta: [src/agent/skills/catalog/](/src/agent/skills/catalog/)
- Arquivo: [README.md](/src/agent/skills/README.md)
- Arquivo: [__init__.py](/src/agent/skills/__init__.py)
- Arquivo: [builtins.py](/src/agent/skills/builtins.py)
- Arquivo: [discovery.py](/src/agent/skills/discovery.py)
- Arquivo: [models.py](/src/agent/skills/models.py)
- Arquivo: [selector.py](/src/agent/skills/selector.py)

- Subpasta: [src/agent/skills/authoring/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/)
## `src/agent/skills/authoring/`

**Propósito:** Autoração de skills pelo próprio agente: layout, validação, instalação, versionamento e histórico.

- Subpasta: [src/agent/skills/authoring/](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/)
- Arquivo: [__init__.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/__init__.py)
- Arquivo: [layout.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/layout.py)
- Arquivo: [service.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/service.py)
- Arquivo: [store.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/store.py)
- Arquivo: [validator.py](/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/skills/authoring/validator.py)
## `src/agent/skills/catalog/`

**Propósito:** Leitura do catálogo de Skills em Markdown (fonte de verdade).

- Arquivo: [__init__.py](/src/agent/skills/catalog/__init__.py)
- Arquivo: [loader.py](/src/agent/skills/catalog/loader.py)

### `src/agent/skills/catalog/__init__.py`

**Propósito:** Re-exporta o carregador do catálogo de Skills em Markdown (fonte de verdade das competências).

### `src/agent/skills/catalog/loader.py`

**Propósito:** Converte o catálogo de Skills em Markdown (`skills/*.md`) em objetos `SkillSpec`, sendo a fonte de verdade das competências profissionais do agente. **Quando/onde:** Usado na descoberta (`SkillRegistry.reload`) para carregar as Skills do repositório e do projeto.

- `_as_list(value: object) -> list[str]` — Normaliza um valor do front matter (escalar, lista ou `None`) em uma lista de textos não vazios. Usado para campos como `keywords`, `required_tools` e `examples`.
- `_section_key(header: str) -> str | None` — Mapeia o título de uma seção Markdown para o campo correspondente do `SkillSpec` (procedimentos, validação, riscos, critérios de ativação, proibições, ferramentas, exemplos). Retorna `None` quando a seção não é mapeada.
- `_split_list(value: str) -> list[str]` — Divide um valor de lista inline (`[a, b]`) em itens, removendo colchetes, aspas e espaços em volta. Retorna a lista de itens de string.
- `catalog_dir(project_root: str | Path | None=None) -> Path | None` — Resolve o catálogo a usar: `<project_root>/skills` quando existe, senão o catálogo do repositório. Retorna `None` quando nenhum catálogo está disponível.
- `default_catalog_dir() -> Path | None` — Localiza o catálogo `skills/` shipped com o repositório, reconhecendo a raiz pelo `pyproject.toml` e exigindo ao menos um `.md` dentro. Retorna `None` quando o pacote foi instalado sem o repositório.
- `load_catalog(directory: str | Path | None=None, *, strict: bool=True) -> list[SkillSpec]` — Lê todos os `.md` do diretório de catálogo (ignorando `README.md`), converte cada um e descarta — com log — os inválidos quando `strict` é verdadeiro. Retorna a lista de `SkillSpec`; arquivo corrompido nunca derruba a execução.
- `parse_frontmatter(text: str) -> tuple[dict[str, object], str]` — Separa o front matter YAML-like do corpo do Markdown, aceitando escalares, listas inline (`chave: [a, b]`) e listas em bloco (`chave:` seguido de linhas `- item`). Retorna o dicionário de metadados e o corpo restante.
- `parse_skill_markdown(text: str, *, source_path: str | Path | None=None) -> SkillSpec` — Converte um Markdown de Skill em `SkillSpec` completo: id (do front matter ou do nome do arquivo), nome, descrição (do front matter, da seção "Descrição" ou do primeiro parágrafo) e as listas de critérios, proibições, ferramentas, procedimentos, validação, riscos, exemplos, keywords e `applies_to_kinds`. Retorna sempre uma instância, mesmo com campos vazios.
- `_read_manifest(path: Path) -> dict[str, object]` — Lê o `manifest.json` de uma skill em pasta, ou dicionário vazio quando o arquivo falta ou é ilegível.
- `_list_files(root: Path, folder: str) -> list[str]` — Lista os arquivos de uma subpasta opcional da skill (`scripts`, `references`, `assets`, `tests`).
- `_load_skill_folders(base: Path, *, strict: bool) -> list[SkillSpec]` — Carrega skills no formato de pasta (`SKILL.md` + manifesto), sem executar scripts.

### `src/agent/skills/README.md`

**Propósito:** Índice da pasta `skills/` do agente — contrato, catálogo, descoberta, seleção e injeção das competências no prompt.

### `src/agent/skills/__init__.py`

**Propósito:** Pacote de Skills do Agente — re-exporta `SkillSpec`, `SkillMatch`, `SkillRegistry`, `SkillSelector`, `get_builtin_skills`.

### `src/agent/skills/builtins.py`

**Propósito:** Catálogo de Skills profissionais nativas.

- `get_builtin_skills() -> list[SkillSpec]` — 6 skills: `software_engineering`, `debugging_root_cause`, `testing_quality_assurance`, `refactoring_clean_code`, `system_architecture`, `technical_writing`.

### `src/agent/skills/discovery.py`

**Propósito:** Mantém o registro central de Skills do agente, combinando skills embutidas, catálogo do repositório e skills do projeto, e expondo sua origem e erros de validação. **Quando/onde:** Usado pelo `SkillSelector` e pelo construtor de contexto para obter as Skills disponíveis na raiz do projeto atual.

- `SkillRegistry` — carrega built-ins e descobre skills no diretório `skills/`.
- `SkillRegistry.__init__(project_root: str | Path | None=None) -> None` — Inicializa o registro com a raiz do projeto (quando informada) e dispara `reload()`, que carrega as skills embutidas e depois as do catálogo do projeto e do repositório, com precedência do projeto por identificador.
- `SkillRegistry._catalog_dirs() -> list[Path]` — Lista os diretórios de catálogo por ordem de especificidade: `<project_root>/skills` primeiro e, se distinto, o catálogo genérico do repositório. Retorna a lista de diretórios existentes.
- `SkillRegistry._register(skill: SkillSpec, *, source: str) -> None` — Valida a Skill e, se válida, a indexa por id guardando a origem; se inválida, registra os erros em `_invalid_skills` e emite warning sem interromper o carregamento.
- `SkillRegistry.get(skill_id: str) -> SkillSpec | None` — Devolve a Skill pelo identificador ou `None` quando ela não existe no catálogo.
- `SkillRegistry.list_all() -> list[SkillSpec]` — Devolve todas as Skills válidas do catálogo (embutidas + repositório + projeto).
- `SkillRegistry.list_invalid() -> dict[str, list[str]]` — Devolve uma cópia do mapa de Skills inválidas e seus erros de validação, indexado por id. Usado para diagnóstico e testes.
- `SkillRegistry.register(skill: SkillSpec) -> None` — Registra programaticamente uma Skill em tempo de execução, com origem "runtime"; se a validação falhar, guarda os erros e levanta `ValueError`.
- `SkillRegistry.reload() -> None` — recarrega catálogo; valida e separa skills inválidas.
- `SkillRegistry.source_of(skill_id: str) -> str | None` — Informa a origem da Skill carregada (`builtin`, caminho do catálogo ou "runtime"). Retorna `None` se o id não estiver registrado.
- `get_skill_registry(project_root: str | Path | None=None) -> SkillRegistry` — instância singleton.
- `installed_skills_dir() -> Path` — Pasta das skills instaladas pelo agente (`data/skills`).
- `reset_skill_registry() -> None` — Descarta o singleton do registro, forçando o recarregamento na próxima chamada a `get_skill_registry`. Usado em testes e ao trocar de projeto em runtime.

### `src/agent/skills/models.py`

**Propósito:** Define o contrato formal de dados de uma Skill (`SkillSpec`) e o resultado de matching (`SkillMatch`), além da validação e da renderização para prompt. **Quando/onde:** Usado por todo o pacote `agent.skills` para representar e validar competências.

- `SkillMatch` — resultado do matching.
- `SkillSpec` — metadados, critérios de ativação/proibição, procedimentos, validação, ferramentas.
- `SkillSpec.is_valid() -> bool` — Indica se a Skill satisfaz todos os requisitos do contrato (id, name, description e procedimentos ou critérios de ativação). Retorna `True` quando `validate()` não produz erros.
- `SkillSpec.render_prompt_instructions(max_chars: int=1500) -> str` — bloco condensado para injeção no prompt.
- `SkillSpec.validate() -> list[str]` — valida integridade do contrato.

### `src/agent/skills/selector.py`

**Propósito:** Motor de seleção sob demanda de Skills, que pontua o objetivo contra as Skills registradas e injeta apenas as instruções relevantes no prompt. **Quando/onde:** Usado na montagem do contexto da operação (`OperationContextBuilder._skills_block`) e por qualquer fluxo que precise escolher competências.

- `SkillSelector` — seleciona até `max_skills` competências por palavras-chave, kind e ferramentas.
- `SkillSelector.__init__(registry: SkillRegistry | None=None) -> None` — Cria o seletor usando o registro informado ou, na ausência dele, o singleton `get_skill_registry()`. Define a origem da lista de Skills candidatas.
- `SkillSelector._prohibited(skill: SkillSpec, lower_obj: str, words: set[str]) -> bool` — Aplica os critérios de não-ativação da Skill: descarta quando o objetivo é de leitura pura e a Skill exige alteração, ou quando o critério negativo ("não use para X") casa com o objetivo. Retorna `True` se a Skill não puder ser usada.
- `SkillSelector.render_selected_skills(matches: list[SkillMatch], *, max_chars: int=2500) -> str` — bloco de instruções dentro do orçamento.
- `SkillSelector.select(objective: str, *, task_kind: str | None=None, available_tools: Sequence[str] | None=None, max_skills: int=2) -> list[SkillMatch]` — Seleciona as Skills relevantes para o objetivo (palavras-chave, tipo de tarefa e ferramentas disponíveis), respeitando os critérios de não-ativação; devolve até `max_skills` `SkillMatch` ordenados por relevância.
- `SkillSelector.select_for_strategy(strategy: object, *, task_kind: str | None=None, available_tools: Sequence[str] | None=None, max_skills: int=2) -> list[SkillMatch]` — Seleciona Skills a partir de uma `ProfessionalStrategy`: usa o objetivo original da estratégia, bonifica a especialidade líder (+10) e as revisoras (+5) e completa com os demais matches ordenados por score, respeitando `max_skills`. Retorna a lista de `SkillMatch` escolhidos.
- `_overlaps(phrase: str, lower_obj: str) -> bool` — Indica se ao menos uma palavra significativa (4+ caracteres) da frase aparece como palavra inteira no objetivo. Retorna `False` quando a frase não tem palavras relevantes.
- `_word_pattern(term: str) -> re.Pattern[str]` — Compila um padrão de palavra inteira (`(?<!\w)termo(?!\w)`) para o termo em minúsculas, evitando casar `api` dentro de `rapido`. Retorna o `re.Pattern` pronto para `search`.

## `src/agent/tools/`

**Propósito:** Registro central de ferramentas e as builtins (arquivos, comandos, git, testes, browser).

- Arquivo: [README.md](/src/agent/tools/README.md)
- Arquivo: [browser.py](/src/agent/tools/browser.py)
- Arquivo: [builtins.py](/src/agent/tools/builtins.py)
- Arquivo: [diffing.py](/src/agent/tools/diffing.py)
- Arquivo: [registry.py](/src/agent/tools/registry.py)

### `src/agent/tools/README.md`

**Propósito:** Índice da pasta `tools/`.

### `src/agent/tools/browser.py`

**Propósito:** navegador local via Playwright (janela visível ou headless) e busca textual na web, com uma única página mantida viva entre as etapas. **Quando/onde:** usado pela ferramenta `browser` quando o compositor liga o navegador, preservando o estado do site entre chamadas do agente.

- `BrowserSession` — gerencia browser persistente (uma instância por sessão).
- `BrowserSession.__init__() -> None` — cria a fila de ações e sobe a thread daemon que mantém o navegador vivo entre chamadas. Entrada: nenhuma; saída: `None`.
- `BrowserSession._loop() -> None` — laço infinito da thread: consome ações da fila, reabre o Chromium quando o modo (headless/visível) muda e devolve o resultado na fila de resposta da chamada. Entrada: item `(action, args, headed, box)` da fila; saída: `None` (o resultado vai para a fila da chamada). Quando o `BrowserSession` está ativo.
- `BrowserSession.call(action: str, args: dict, *, headed: bool, timeout: float=45) -> dict` — enfileira uma ação e espera o resultado da thread, devolvendo erro de tempo esgotado se ela não responder. Entrada: ação, argumentos, modo visível/headless e limite de espera; saída: dicionário de resultado ou `{"success": False, "error": "navegador demorou demais"}`.
- `_watch_page(page, console_log: list[dict], network_log: list[dict]) -> None` — Registra console e respostas HTTP da página, sem cabeçalhos e com segredos redigidos.
- `_act(page, action: str, args: dict, *, headed: bool, console_log: list[dict] | None=None, network_log: list[dict] | None=None) -> dict` — executa uma ação do Playwright (`navigate`, `snapshot`, `click`, `type`, `fill`, `press`, `scroll`, `screenshot`, `aria`, `console`, `network`) e devolve o resultado. Campo de senha não devolve o valor.
- `_launch(playwright, headed: bool)` — abre o Chromium, preferindo o canal `chrome` e caindo para o Chromium embutido quando o primeiro falha. Entrada: contexto do Playwright e flag de janela visível; saída: objeto `Browser`.
- `browser_call(action: str, args: dict, *, headed: bool) -> dict` — actions: `navigate`, `click`, `fill`, `screenshot`, `evaluate`, `select`, `hover`, `wait`, `close`.
- `guard_url(url: str) -> str` — valida URL (https, não localhost/private).
- `parse_search_html(html: str, limit: int=5) -> list[dict]` — extrai resultados.
- `search_web(query: str, limit: int=5) -> dict` — busca DuckDuckGo/Google, parse HTML.

### `src/agent/tools/builtins.py`

**Propósito:** implementa as ferramentas locais do agente (arquivos, busca, comandos, testes, git, memória, navegador) e as registra no `ToolRegistry`. **Quando/onde:** é o conjunto principal de handlers executado pelo `ToolRegistry.execute` quando o modelo pede uma ferramenta local.

- `_argv(command: object) -> list[str] | None` — normaliza o comando pedido pelo modelo: string vira lista via `shlex.split`, lista de strings é usada como está (com split se tiver um item com espaço) e qualquer outro valor devolve `None`. Entrada: `command` cru; saída: argv ou `None`. Quando `_run_command` monta a execução.
- `_browser(ctx: ToolContext, args: dict) -> dict` — atende a ferramenta `browser`: recusa se o navegador estiver desligado, faz busca textual via DuckDuckGo ou delega as demais ações à `BrowserSession` em thread. Entrada: contexto e args (`action`, `url`, `text`, `selector`, `query`); saída: dicionário com o resultado da ação.
- `_delete_file(ctx: ToolContext, args: dict) -> dict` — apaga um arquivo dentro da raiz do projeto e emite o evento `file.deleted`. Entrada: `path`; saída: `{"success": True, "path": ...}` ou erro (arquivo inexistente, caminho fora do escopo).
- `_drop_stale_bytecode(path: Path) -> None` — remove o `.pyc` cacheado do `.py` correspondente em `__pycache__`, evitando que o Python execute a versão antiga do arquivo. Entrada: caminho do `.py`; saída: `None`. Quando um arquivo é escrito ou editado.
- `_edit_file(ctx: ToolContext, args: dict) -> dict` — substitui um trecho do arquivo (`old_string`→`new_string`, com apelidos `old`/`new`/`replace`/`replacement`), exigindo trecho único salvo `replace_all`, e devolve o diff. Entrada: `path` e o par antigo/novo; saída: dicionário com `replacements` e o diff unificado.
- `_file_event(event_type: str, path: str, diff: dict | None=None, **extra: object) -> None` — publica o evento de arquivo (`file.read`, `file.changed`, ...) já ligado ao `call_id` da ferramenta em curso; em caminho sensível, publica só as contagens e marca `sensitive`. Entrada: tipo de evento, caminho, diff opcional e campos extras; saída: `None`.
- `_git_diff(ctx: ToolContext, args: dict) -> dict` — roda `git -C <raiz> diff` com as opções `--stat`, `--cached` e `-- <path>`, truncando a saída em 12000 caracteres. Entrada: args opcionais; saída: dicionário com `success`, `stdout`, `stderr` e `truncated`.
- `_git_status(ctx: ToolContext, args: dict) -> dict` — roda `git -C <raiz> status --short` na raiz do projeto. Entrada: contexto; saída: dicionário com `success`, `stdout` (até 8000 caracteres) e `stderr`.
- `_glob_files(ctx: ToolContext, args: dict) -> dict` — casa o glob pedido contra a árvore do projeto, recusando padrões absolutos ou com `..` e pulando diretórios ignorados. Entrada: `pattern`; saída: `{"success": True, "matches": [...], "truncated": ...}`.
- `_list_dir(ctx: ToolContext, args: dict) -> dict` — lista o conteúdo de um diretório (recursivo com `recursive`), ignorando `.git`, `node_modules`, `__pycache__` e afins, e ordena diretórios antes de arquivos. Entrada: `path` e `recursive`; saída: `{"success": True, "entries": [...], "truncated": ...}`.
- `_make_dir(ctx: ToolContext, args: dict) -> dict` — cria o diretório dentro da raiz com `parents=True`; falha se o caminho já for um arquivo. Entrada: `path`; saída: `{"success": True, "path": ...}` ou erro.
- `_move_file(ctx: ToolContext, args: dict) -> dict` — move/renomeia um arquivo dentro do projeto (aceita `from`/`source`/`path` e `to`/`dest`/`destination`), cria o diretório de destino e emite `file.deleted` + `file.created`. Entrada: origem e destino; saída: `{"success": True, "from": ..., "to": ...}` ou erro.
- `_pump(stream: asyncio.StreamReader | None, chunks: list[bytes], batcher: DeltaBatcher) -> None` — lê o stream do subprocesso em blocos de 4096 bytes, decodifica incrementalmente em UTF-8 e entrega os textos ao `DeltaBatcher` enquanto guarda os bytes crus. Entrada: stream, lista de chunks e batcher; saída: `None` (encerra no EOF). Quando `_run_command` consome stdout/stderr.
- `_read_file(ctx: ToolContext, args: dict) -> dict` — lê o arquivo com paginação por `offset`/`limit`, corta em 400 linhas quando não há limite e emite o evento `file.read`. Entrada: `path` e paginação; saída: dicionário com `content`, `offset`, `total_lines` e `truncated`.
- `_remember(ctx: ToolContext, args: dict) -> dict` — grava uma memória delegando ao `memory_saver` do contexto, com `content`, `title` e `scope` (`project`/`conversation`). Entrada: args da memória; saída: o que o `memory_saver` devolver, ou erro quando não há memória disponível.
- `_resolve(ctx: ToolContext, raw: str) -> tuple[Path | None, dict | None]` — resolve path seguro via `resolve_under_root`.
- `_root(ctx: ToolContext) -> Path` — devolve a raiz do projeto resolvida a partir de `ctx.project_root`. Entrada: contexto; saída: `Path` absoluto. Quando as ferramentas de arquivo calculam caminhos relativos.
- `_run_command(ctx: ToolContext, args: dict, *, kind: str='command') -> dict` — executa o comando como subprocesso assíncrono, emitindo a saída em tempo real, matando o processo no timeout e devolvendo `exit_code`, `stdout` e `stderr` truncados. Entrada: `command` (lista ou string), `cwd`, `env` e `timeout`; saída: dicionário com `success`, `exit_code` e as saídas.
- `_run_pytest(ctx: ToolContext, args: dict) -> dict` — roda `python -m pytest -q -p no:cacheprovider` no alvo, com `PYTHONDONTWRITEBYTECODE=1` para não deixar `.pyc` obsoleto, e extrai os contadores do resumo. Entrada: `path` opcional e `timeout`; saída: dicionário de comando acrescido de `counts` (`passed`, `failed`, ...).
- `_run_script(ctx: ToolContext, args: dict) -> dict` — executa um `.py` do projeto com o interpretador do venv local, colocando o pacote no `PYTHONPATH` (usa a raiz extra em scripts dentro de `tests/`). Entrada: `path` e `timeout`; saída: dicionário de comando com o resultado da execução.
- `_search_grep(ctx: ToolContext, args: dict) -> dict` — busca uma regex nos arquivos do projeto (ou em `path`), pulando binários e diretórios ignorados e parando em 100 ocorrências. Entrada: `pattern`/`query` e `path`; saída: `{"success": True, "matches": [{path, line, text}], "count": n}`.
- `_skipped(rel: Path) -> bool` — diz se um caminho relativo está dentro de um diretório ignorado (`.git`, `node_modules`, `__pycache__`, `.venv`, caches). Entrada: caminho relativo; saída: booleano. Quando listagem, glob e grep filtram resultados.
- `_system_info(ctx: ToolContext, args: dict) -> dict` — descreve a máquina: sistema, release, arquitetura, versão do Python, usuário, pasta pessoal, hora local e raiz do workspace. Entrada: contexto; saída: dicionário com os dados do ambiente.
- `_test_counts(stdout: str) -> dict[str, int]` — extrai do último resumo do pytest as quantidades de passed/failed/error/skipped. Entrada: stdout do pytest; saída: dicionário `{"passed": n, "failed": n, ...}`.
- `_write_file(ctx: ToolContext, args: dict) -> dict` — grava o conteúdo no arquivo, criando diretórios quando preciso, remove o bytecode obsoleto e emite `file.created`/`file.changed` com o diff. Entrada: `path` e `content`; saída: dicionário com `bytes`, `created` e o diff.
- `python_for(project_root: str) -> str` — escolhe o interpretador do projeto: o `python` do `.venv`/`venv` se existir, senão o `sys.executable` do agente. Entrada: raiz do projeto; saída: caminho do interpretador. Quando `_run_command`, `_run_script` e `_run_pytest` montam o argv.
- `register_all(registry: ToolRegistry) -> None` — registra todas builtins.

- `_run_command_remote(ctx, args, *, kind) → dict` — Comando executado no computador remoto do projeto (SSH), com saída em tempo real.
- `_out(stream) → DeltaBatcher` — Monta a resposta da ferramenta com a saída capturada e o código de saída.
- `_out(text) → None` — Monta a resposta da ferramenta com a saída capturada e o código de saída.
### `src/agent/tools/diffing.py`

**Propósito:** Diff unificado textual (para `file_edit` emitir diff).

- `unified_diff_text(path: str, before: str, after: str, *, limit: int=4000) -> dict` — `added`, `removed`, `diff` (unified diff string).

### `src/agent/tools/registry.py`

**Propósito:** registro central de ferramentas: guarda specs e handlers, resolve apelidos de nome, aplica aprovação obrigatória e emite os eventos de execução. **Quando/onde:** usado pelo orquestrador para validar e despachar toda chamada de ferramenta do modelo.

- `ToolContext` — contexto de execução.
- `ToolRegistry` — Símbolo do módulo — ver a descrição do arquivo.
- `ToolRegistry.__init__() -> None` — cria o registro vazio de especificações e handlers. Entrada: nenhuma; saída: `None`.
- `ToolRegistry.execute(tool_id: str, ctx: ToolContext, args: dict[str, Any], *, approved: bool=False) -> dict[str, Any]` — executa com timeout, emite eventos, valida aprovação.
- `ToolRegistry.get_spec(tool_id: str) -> ToolSpec` — schema da ferramenta.
- `ToolRegistry.list_specs() -> list[ToolSpec]` — catálogo para o modelo.
- `ToolRegistry.register(spec: ToolSpec, handler: ToolHandler) -> None` — registra.
- `ToolSpec(BaseModel)` — Especificação de uma ferramenta: id, nome, descrição, kind, schema JSON dos parâmetros, aliases, timeout, exigência de aprovação e categorias.
- `_args_preview(args: dict[str, Any]) -> dict[str, Any]` — prepara os argumentos para o evento de início da ferramenta, trocando conteúdos longos de arquivo por `[N caracteres]`. Entrada: args; saída: dicionário para exibição. Quando `ToolRegistry.execute` emite `tool.started`.
- `_ms(started: float) -> int` — converte o instante inicial (de `time.monotonic`) em milissegundos decorridos. Entrada: timestamp inicial; saída: inteiro de milissegundos. Quando o registro calcula a duração da chamada.
- `_summary(result: dict[str, Any]) -> dict[str, Any]` — extrai do resultado só as chaves de resumo (`path`, `exit_code`, `count`, `bytes`, `added`, `removed`, etc.) para anexar aos eventos. Entrada: resultado da ferramenta; saída: dicionário resumido. Quando a chamada termina com sucesso ou falha.
- `build_default_registry() -> ToolRegistry` — carrega todos builtins + browser se Playwright.
- `canonical_tool_id(tool_id: str) -> str` — resolve alias → canônico.
- `current_call_id() -> str | None` — devolve o id da chamada de ferramenta em andamento, guardado num `ContextVar`. Entrada: nenhuma; saída: id hex ou `None`. Quando comandos e eventos de arquivo se ligam à chamada que os disparou.
- `ToolContext.cancelled() -> bool` — Indica se o cancelamento cooperativo foi pedido para esta execução.
- `ToolRegistry.ids() -> list[str]` — Identificadores registrados, em ordem alfabética.
- `ToolRegistry.specs_of_family(family: str) -> list[ToolSpec]` — Ferramentas de uma família.
- `ToolRegistry.compact_catalog(families: list[str] | None=None) -> str` — Catálogo de uma linha por ferramenta, para o prompt.
- `ToolRegistry.describe(tool_id: str) -> dict[str, Any]` — Contrato completo e pré-requisitos de uma ferramenta, sob demanda.
- `ToolRegistry.availability_report() -> list[dict[str, Any]]` — O que falta para cada ferramenta registrada.
- `get_default_registry() -> ToolRegistry` — Registro padrão do processo, montado uma vez.
- `_tool_catalog(ctx: ToolContext, args: dict) -> dict` — Lista as ferramentas registradas quando o modelo pede o catálogo.
- `_tool_help(ctx: ToolContext, args: dict) -> dict` — Detalha uma ferramenta quando o modelo pede ajuda.

### `src/agent/tools/arguments.py`

**Propósito:** validar os argumentos de uma ferramenta contra o esquema declarado, antes da execução.

- `validate_arguments(schema: dict[str, Any] | None, args: dict[str, Any] | None) -> str | None` — Confere presença e tipo; devolve a mensagem do erro ou `None`.
- `_validate_shorthand(schema: dict[str, str], args: dict[str, Any]) -> str | None` — Valida o atalho `nome: tipo` (`str?`, `str|list[str]`).
- `_validate_json_schema(schema: dict[str, Any], args: dict[str, Any]) -> str | None` — Valida o JSON Schema usado pelas automações.
- `_matches_union(body: str, value: Any) -> bool` — Indica se o valor casa com algum tipo unido por `|`.
- `_matches_atom(atom: str, value: Any) -> bool` — Indica se o valor casa com um tipo ou um literal.
- `_matches_json_property(prop: dict[str, Any], value: Any) -> bool` — Indica se o valor casa com uma propriedade de JSON Schema.

### `src/agent/tools/availability.py`

**Propósito:** verificar se os pré-requisitos de uma ferramenta existem no ambiente atual.. camada de infraestrutura — sondagem de binários, módulos, sistema e ambiente.

- `Requirement` — Um pré-requisito verificável de uma ferramenta.
- `Requirement.parse(spec: str) -> Requirement` — Interpreta a forma textual do requisito.
- `Availability` — Resultado da verificação de pré-requisitos de uma ferramenta.
- `_current_os() -> str` — Nome canônico do sistema operacional atual.
- `_has_gui_session() -> bool` — Indica se há sessão gráfica ativa no ambiente atual.
- `check_requirement(requirement: Requirement) -> tuple[bool, str, str]` — Verifica um pré-requisito.
- `check_requirements(requirements: list[str]) -> Availability` — Verifica uma lista de requisitos.
- `check_tool(spec: Any) -> Availability` — Verifica os requisitos declarados por uma ferramenta.
- `environment_report() -> dict[str, Any]` — Descreve o ambiente de execução para o diagnóstico.
### `src/agent/tools/catalog.py`

**Propósito:** decidir quais ferramentas o modelo recebe em cada etapa, sem estourar o contexto.. camada de aplicação — exposição de capacidades por objetivo e configuração.

- `enabled_families(settings: Any=None) -> set[str] | None` — Famílias de ferramentas liberadas pela configuração.
- `families_for_objective(objective: str) -> set[str]` — Famílias extras sugeridas pelo texto do pedido.
- `exposed_tools(registry: ToolRegistry, *, objective: str='', base: Iterable[str]=(), settings: Any=None) -> tuple[str, ...]` — Ferramentas oferecidas ao modelo em uma etapa.
- `capability_summary(registry: ToolRegistry, tool_ids: Iterable[str]) -> str` — Resumo compacto das capacidades expostas, para o prompt.
### `src/agent/tools/contracts.py`

**Propósito:** definir os contratos estáveis da camada de ferramentas (risco, permissões, execução).. camada de infraestrutura — vocabulário compartilhado entre registro, política e adaptadores.

- `ToolRisk(str, Enum)` — Nível de risco de uma ferramenta, do mais seguro ao mais perigoso.
- `ExecutionMode(str, Enum)` — Como a ferramenta roda, do ponto de vista do agente.
- `ToolFamily(str, Enum)` — Família funcional da ferramenta — a unidade habilitada e desabilitada em conjunto.
- `risk_at_least(risk: str | ToolRisk, minimum: str | ToolRisk) -> bool` — Indica se um nível de risco atinge um piso.
- `risk_above(risk: str | ToolRisk, ceiling: str | ToolRisk) -> bool` — Indica se um nível de risco ultrapassa um teto.
### `src/agent/tools/desktop_tools.py`

**Propósito:** expor ao agente a automação de desktop: tela, entrada, janelas e screenshots.. camada de apresentação — handlers das ferramentas de interface gráfica.

- `_screen(ctx: ToolContext, args: dict) -> dict` — Informa a geometria da tela e as limitações da sessão.
- `_screenshot(ctx: ToolContext, args: dict) -> dict` — Captura a tela inteira ou uma região.
- `_click(ctx: ToolContext, args: dict) -> dict` — Clica em um ponto da tela.
- `_drag(ctx: ToolContext, args: dict) -> dict` — Arrasta o ponteiro de um ponto a outro.
- `_type(ctx: ToolContext, args: dict) -> dict` — Digita um texto na janela em foco.
- `_key(ctx: ToolContext, args: dict) -> dict` — Pressiona uma tecla ou um atalho.
- `_scroll(ctx: ToolContext, args: dict) -> dict` — Rola a tela.
- `_windows(ctx: ToolContext, args: dict) -> dict` — Lista as janelas visíveis da sessão gráfica.
- `_elements(ctx: ToolContext, args: dict) -> dict` — Lista os elementos da janela pela árvore de acessibilidade.
- `_wait(ctx: ToolContext, args: dict) -> dict` — Espera uma janela pelo título ou um elemento pelo nome.
- `_click_element(ctx: ToolContext, args: dict) -> dict` — Clica em um elemento localizado pelo nome, relendo a geometria na hora.
- `register_all(registry: ToolRegistry) -> None` — Registra as ferramentas de automação de desktop.
### `src/agent/tools/devtools.py`

**Propósito:** expor ao agente a descoberta de projetos, o Git e a execução de verificações de qualidade.. camada de apresentação — handlers das ferramentas de engenharia de software.

- `_project_info(ctx: ToolContext, args: dict) -> dict` — Descreve o projeto: linguagem, manifestos, gerenciadores e instruções.
- `_project_commands(ctx: ToolContext, args: dict) -> dict` — Deriva os comandos de instalação, build, lint, teste e execução.
- `_read_manifest(ctx: ToolContext, args: dict) -> dict` — Lê um manifesto de projeto (package.json, pyproject.toml, Cargo.toml).
- `_git_branch(ctx: ToolContext, args: dict) -> dict` — Branches do repositório Git, com a atual em destaque.
- `_git_log(ctx: ToolContext, args: dict) -> dict` — Histórico recente de commits.
- `_run_check(ctx: ToolContext, args: dict) -> dict` — Executa uma verificação de qualidade (lint, teste ou build) e resume o resultado.
- `register_all(registry: ToolRegistry) -> None` — Registra as ferramentas de engenharia de software.
### `src/agent/tools/policy.py`

**Propósito:** decidir se uma ferramenta pode rodar, com que risco e se precisa de aprovação humana.. camada de infraestrutura — política de permissões por ferramenta, família e sessão.

- `PolicyDecision` — Veredito da política sobre uma chamada de ferramenta.
- `PermissionPolicy` — Política de permissões do agente: o que é liberado, o que exige aprovação, o que é proibido.
- `PermissionPolicy.disable_family(family: str) -> None` — Desliga uma família de ferramentas nesta sessão.
- `PermissionPolicy.enable_family(family: str) -> None` — Religa uma família de ferramentas nesta sessão.
- `PermissionPolicy.grant(tool_id: str) -> None` — Concede aprovação pontual para uma ferramenta nesta sessão.
- `PermissionPolicy.decide(tool_id: str, *, risk: ToolRisk=ToolRisk.READ, family: str='', approved: bool=False) -> PolicyDecision` — Decide se a chamada pode rodar e se exige aprovação.
- `PermissionPolicy.from_config(config: dict[str, Any] | None) -> PermissionPolicy` — Constrói a política a partir de um dicionário de configuração.
- `PermissionPolicy.to_config() -> dict[str, Any]` — Serializa a política para configuração.
- `redact_text(text: str) -> str` — Remove segredos de um texto livre.
- `redact(value: Any) -> Any` — Remove segredos de uma estrutura de dados qualquer, preservando a forma.
- `is_secret_env(name: str) -> bool` — Indica se uma variável de ambiente provavelmente guarda um segredo.
- `tool_policy(settings: Any=None) -> PermissionPolicy` — Monta a política de permissões a partir da configuração do processo.
### `src/agent/tools/skill_tools.py`

**Propósito:** expor ao agente o ciclo de vida das skills: criar, validar, testar, instalar e ativar.. camada de apresentação — handlers das ferramentas de autoria e gestão de skills.

- `_service() -> SkillAuthoringService` — Serviço de autoria, recriado quando a pasta de skills mudou.
- `_skill_list(ctx: ToolContext, args: dict) -> dict` — Lista as skills conhecidas: instaladas, do projeto e do catálogo.
- `_skill_search(ctx: ToolContext, args: dict) -> dict` — Pesquisa skills por nome, descrição ou palavra-chave.
- `_skill_create(ctx: ToolContext, args: dict) -> dict` — Cria uma skill em estado de rascunho a partir de um pedido.
- `_skill_validate(ctx: ToolContext, args: dict) -> dict` — Valida o contrato de uma skill instalada.
- `_skill_test(ctx: ToolContext, args: dict) -> dict` — Executa os testes de uma skill em ambiente isolado.
- `_skill_install(ctx: ToolContext, args: dict) -> dict` — Instala uma skill a partir de uma pasta externa, sem executar o conteúdo.
- `_skill_activate(ctx: ToolContext, args: dict) -> dict` — Ativa uma skill validada.
- `_skill_deactivate(ctx: ToolContext, args: dict) -> dict` — Desativa uma skill sem apagar o conteúdo.
- `_skill_update(ctx: ToolContext, args: dict) -> dict` — Atualiza uma skill a partir de uma nova versão, preservando o histórico.
- `_skill_history(ctx: ToolContext, args: dict) -> dict` — Mostra o histórico de alterações de uma skill.
- `_skill_propose(ctx: ToolContext, args: dict) -> dict` — Registra uma proposta de melhoria de skill, com a evidência que a motivou.
- `_skill_resolve_proposal(ctx: ToolContext, args: dict) -> dict` — Aceita ou rejeita uma proposta de melhoria.
- `_strings(value: Any) -> list[str]` — Normaliza um argumento de lista de textos.
- `register_all(registry: ToolRegistry) -> None` — Registra as ferramentas de ciclo de vida de skills.
### `src/agent/tools/system_tools.py`

**Propósito:** expor ao agente o gerenciamento de processos, aplicativos e diagnóstico do sistema.. camada de apresentação — handlers das ferramentas de sistema e de rede.

- `_root(ctx: ToolContext) -> Path` — Raiz absoluta do projeto autorizada no contexto.
- `_resolve(ctx: ToolContext, raw: str) -> tuple[Path | None, dict | None]` — Resolve um caminho dentro da raiz do projeto, devolvendo o erro em vez de levantá-lo.
- `_diagnose(ctx: ToolContext, args: dict) -> dict` — Diagnostica o ambiente: sistema, sessão, permissões e dependências.
- `_list_processes(ctx: ToolContext, args: dict) -> dict` — Lista os processos em execução.
- `_process_info(ctx: ToolContext, args: dict) -> dict` — Inspeciona um processo pelo identificador.
- `_kill_process(ctx: ToolContext, args: dict) -> dict` — Encerra um processo autorizado.
- `_list_apps(ctx: ToolContext, args: dict) -> dict` — Lista os aplicativos instalados.
- `_launch_app(ctx: ToolContext, args: dict) -> dict` — Abre um aplicativo, com argumentos, diretório de trabalho e ambiente controlados.
- `_open_path(ctx: ToolContext, args: dict) -> dict` — Abre um arquivo, pasta ou URL com o manipulador padrão do sistema.
- `_task_start(ctx: ToolContext, args: dict) -> dict` — Inicia uma tarefa longa em segundo plano e devolve o identificador.
- `_task_status(ctx: ToolContext, args: dict) -> dict` — Consulta o estado e a saída parcial de uma tarefa em segundo plano.
- `_task_cancel(ctx: ToolContext, args: dict) -> dict` — Cancela uma tarefa em segundo plano.
- `_list_env(ctx: ToolContext, args: dict) -> dict` — Lista as variáveis de ambiente, ocultando os valores sensíveis.
- `_system_resources(ctx: ToolContext, args: dict) -> dict` — Informa uso de disco, memória e carga da CPU.
- `_list_ports(ctx: ToolContext, args: dict) -> dict` — Lista as conexões de rede ativas do sistema.
- `_check_dependencies(ctx: ToolContext, args: dict) -> dict` — Verifica se as dependências pedidas estão disponíveis.
- `_download(ctx: ToolContext, args: dict) -> dict` — Baixa um arquivo para a pasta do projeto, com verificação de tamanho e destino.
- `_file_hash(ctx: ToolContext, args: dict) -> dict` — Calcula o resumo de um arquivo (sha256 por padrão).
- `_archive(ctx: ToolContext, args: dict) -> dict` — Compacta uma pasta ou um arquivo em `.zip` ou `.tar.gz`.
- `_extract_archive(ctx: ToolContext, args: dict) -> dict` — Extrai um arquivo compactado dentro da pasta do projeto.
- `_http_request(ctx: ToolContext, args: dict) -> dict` — Faz uma requisição HTTP para diagnóstico ou integração.
- `register_all(registry: ToolRegistry) -> None` — Registra as ferramentas de sistema, processos, aplicativos e rede.
## `src/agent/util/`

**Propósito:** Utilitários compartilhados (extração tolerante de JSON).

- Arquivo: [README.md](/src/agent/util/README.md)
- Arquivo: [json_parse.py](/src/agent/util/json_parse.py)

### `src/agent/util/README.md`

**Propósito:** Índice da pasta `util/`.

### `src/agent/util/json_parse.py`

**Propósito:** Extração tolerante de JSON de texto do modelo.

- `parse_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]` — encontra primeiro `{`...`}` balanceado, tenta `json.loads`, se falha tenta reparar (aspas simples, trailing commas, etc.).

## `src/agent/verification/`

**Propósito:** Verificações determinísticas independentes e o ciclo de recuperação.

- Arquivo: [README.md](/src/agent/verification/README.md)
- Arquivo: [fingerprint.py](/src/agent/verification/fingerprint.py)
- Arquivo: [recovery.py](/src/agent/verification/recovery.py)
- Arquivo: [runner.py](/src/agent/verification/runner.py)

### `src/agent/verification/README.md`

**Propósito:** Índice da pasta `verification/`.

### `src/agent/verification/fingerprint.py`

**Propósito:** Fingerprint SHA256 de artefatos para detectar mudanças.

- `_files(base: Path, rel: str) -> list[Path]` — expande globs.
- `artifact_paths(spec: dict[str, Any], tool_args: dict[str, Any] | None=None) -> list[str]` — resolve paths dos artefatos declarados no spec.
- `fingerprint(root: str, paths: list[str]) -> str` — hash SHA256 do conteúdo concatenado (ordenado).
- `is_current(artifacts: dict[str, Any] | None) -> bool` — compara fingerprint atual com salvo.
- `snapshot(root: str, spec: dict[str, Any], tool_args: dict[str, Any] | None=None) -> dict[str, Any] | None` — `{fingerprint, paths, mtimes}`.

- `workspace_state(root: str) -> str` — Impressão do estado do disco da raiz inteira (nome, tamanho e mtime de cada arquivo, podando caches e dependências ao descer). É o sinal objetivo de "algo mudou desde a última tentativa": a detecção de repetição do orquestrador usa essa impressão para distinguir uma tentativa legítima de uma repetição improdutiva. Entrada: raiz do projeto; saída: impressão hexadecimal (vazia quando a raiz não existe).
### `src/agent/verification/recovery.py`

**Propósito:** Concentra a taxonomia do diagnóstico de uma verificação reprovada, permitindo o ciclo diagnóstico → correção → re-verificação sem repetir o prompt nem mascarar o sintoma. **Quando/onde:** Usado pelo orquestrador após uma verificação reprovada, para classificar a causa, decidir a ação e montar a orientação da próxima tentativa.

- `RecoveryDiagnosis` — Dataclass que representa o diagnóstico de uma reprovação, com `cause` (taxonomia), `action` a aplicar, `automatic` (se a correção pode ser automática), `guidance` textual ao modelo e `evidence` com as linhas de erro coletadas.
- `RecoveryDiagnosis.as_dict() -> dict[str, Any]` — Serializa o diagnóstico em dicionário com as chaves `cause`, `action`, `automatic`, `guidance` e `evidence`. Usado para persistir o diagnóstico nos metadados da tarefa.
- `_extract_failures(detail: dict[str, Any] | None) -> list[str]` — Extrai do `stdout`/`stderr` do verificador até 5 linhas de asserção ou erro (marcadas por "E " ou por padrões de falha), deduplicadas e truncadas em 200 caracteres. Retorna a lista de evidências.
- `_haystack(summary: str, detail: dict[str, Any] | None) -> str` — Constrói o texto de busca concatenando o resumo com `stdout`, `stderr`, `error`, `reason`, `syntax_error`, `command` e os problemas do detalhe, tudo em minúsculas. É a entrada da classificação por dicas.
- `diagnose_verification_failure(*, verifier: str, summary: str, detail: dict[str, Any] | None=None, spec: dict[str, Any] | None=None) -> RecoveryDiagnosis` — Classifica a causa da reprovação (sintaxe, dependência ausente, timeout, artefato ausente, ambiente, falha de teste ou desconhecida) e devolve o diagnóstico com a ação correspondente (`fix_syntax`, `install_dependency`, `retry`, `regenerate_artifact`, `manual_review`, `fix_tests`), se é automática e a orientação ao modelo. Quando a causa é falha de teste, anexa as asserções como evidência.
- `plan_recovery(diagnosis: RecoveryDiagnosis, *, attempt_count: int=0, max_recoveries: int=2) -> dict[str, Any]` — Decide o próximo passo do ciclo: `block` quando o número de tentativas excedeu o limite, `manual_review` quando a ação não é automática e `fix_and_retry` caso contrário. Retorna o dicionário com `action`, `retry`, `guidance`, `cause` e, no retry, `evidence`.
- `recovery_signature(diagnosis: RecoveryDiagnosis, detail: dict[str, Any] | None=None) -> str` — Gera uma assinatura estável da falha, ignorando números, endereços hexadecimais e espaços repetidos no texto de causa/ação/saída do verificador. Retorna a assinatura normalizada (até 500 caracteres), usada para detectar reincidência.

### `src/agent/verification/runner.py`

**Propósito:** Executa verificações determinísticas (pytest, script, comando, presença de trecho, sintaxe, existência de arquivo, análise estática) contra o projeto e emite eventos de observabilidade. **Quando/onde:** Usado pelo orquestrador para comprovar a entrega de uma etapa antes de marcá-la como concluída.

- `VerificationResult` — Resultado de uma verificação: verificador, veredito (aprovado/reprovado/inconclusivo), resumo, detalhe estruturado e artefatos avaliados.
- `_has_non_python_deliverable(root: str) -> bool` — Verifica se o projeto possui entregáveis não-Python (`.html`, `.css`, `.js`, `.md`, `.tsx`, `.svg`, etc.), ignorando diretórios descartados. Retorna `True` quando existe pelo menos um, permitindo aceitar projetos sem testes Python.
- `_no_tests_collected(out: dict[str, Any]) -> bool` — Detecta que o pytest não coletou nenhum teste, pelo código de saída 5 ou pelas mensagens "no tests ran"/"collected 0 items" na saída. Retorna `True` quando nada foi coletado.
- `_read_whole(project_root: str, path: str) -> dict[str, Any]` — lê arquivo completo para `file_contains`.
- `_verify(*, project_root: str, spec: dict[str, Any], tool_args: dict[str, Any] | None, approved: bool) -> VerificationResult` — despacha por tipo, executa subprocess/validação, captura saída.
- `run_verification(*, project_root: str, spec: dict[str, Any], tool_args: dict[str, Any] | None=None, approved: bool=False) -> VerificationResult` — Executa a verificação determinística pedida no spec (pytest, command, script, file_contains, syntax, file_exists, static_analysis) e devolve o `VerificationResult` com os eventos de verificação emitidos.
- `syntax_problem(path: str, content: str) -> str | None` — `ast.parse` para .py, validação básica outros.

## `src/agent/vision/`

**Propósito:** Referências de imagem para modelos com visão.

- Arquivo: [README.md](/src/agent/vision/README.md)
- Arquivo: [context.py](/src/agent/vision/context.py)

### `src/agent/vision/README.md`

**Propósito:** Índice da pasta `vision/`.

### `src/agent/vision/context.py`

**Propósito:** Referências de imagem para modelos com visão.

- `ImageReference(BaseModel)` — path relativo ao project_root, mime type, detail (low/high/auto).
- `VisionContextBundle(BaseModel)` — Pacote de imagens prontas para o modelo: referências (caminho relativo, mime, detalhe) e data URIs em base64.
- `resolve_images(project_root: str, refs: list[ImageReference]) -> VisionContextBundle` — lê arquivos, converte para base64 data URI.
- `vision_supported(profile: dict) -> bool` — verifica `supports_vision` no perfil.

### `src/agent/README.md`

**Propósito:** mapa dos subpacotes de `agent/` e suas responsabilidades, com link para `config.py` e para a doc de execução local (Ollama como padrão). **Quando/onde:** documentação de navegação.

### `src/agent/__init__.py`

**Propósito:** marca o pacote `agent` e define `__version__ = "0.1.0"` (versão do pacote; a API anuncia sua própria versão, 0.5.0). **Quando/onde:** importado implicitamente em qualquer `import agent...`.

### `src/agent/config.py`

**Propósito:** configuração central lida de variáveis de ambiente e do arquivo `.env` (pydantic-settings). **Quando/onde:** usada pela API (`deps.read_settings`), pela persistência (URL do banco) e pelo orquestrador/provedores (URLs, modelo padrão, limites).

- `Settings(BaseSettings)` — Objeto de configuração (pydantic-settings) com todas as opções do runtime: diretório de dados, URL do banco, provedores e modelos, orçamentos de contexto, limites de tentativas, recursão e run, observabilidade e caminhos da interface.
- `Settings.resolved_database_url() -> str` — Devolve a URL final do SQLite — nos testes força `data_dir/agent.db` para não gravar no banco real; em produção usa `database_url` ou `data/agent.db`, criando o diretório quando necessário.
- `get_settings() -> Settings` — Cria uma instância de `Settings` e, se `mcp_config_path` não foi definido, preenche com `data_dir/mcp.json`. Chamada sempre que alguém precisa da configuração atual.

- `resolved_provider_config_path(self) → Path` — Arquivo de provedores em uso: o configurado ou, por padrão, `data/providers.yaml`.
- `resolved_secrets_dir(self) → Path` — Pasta das credenciais gravadas pela interface (fora do versionamento).

- `Settings.resolved_provider_config_path(self) → Path` — Arquivo de provedores em uso: o configurado ou, por padrão, `data/providers.yaml`.
- `Settings.resolved_secrets_dir(self) → Path` — Pasta das credenciais gravadas pela interface (fora do versionamento).
### `src/README.md`

**Propósito:** índice da pasta `src/`, apontando para o pacote `agent/`. **Quando/onde:** leitura de orientação para quem navega no repositório.

## `tests/`

**Propósito:** Suíte de testes do agente (pytest).

- Subpasta: [tests/fixtures/](/tests/fixtures/)
- Subpasta: [tests/web/](/tests/web/)
- Arquivo: [README.md](/tests/README.md)
- Arquivo: [test_api.py](/tests/test_api.py)
- Arquivo: [test_atomizer.py](/tests/test_atomizer.py)
- Arquivo: [test_attachments.py](/tests/test_attachments.py)
- Arquivo: [test_attempt_loop.py](/tests/test_attempt_loop.py)
- Arquivo: [test_consolidation.py](/tests/test_consolidation.py)
- Arquivo: [test_context_budget.py](/tests/test_context_budget.py)
- Arquivo: [test_context_recovery.py](/tests/test_context_recovery.py)
- Arquivo: [test_contract_impact.py](/tests/test_contract_impact.py)
- Arquivo: [test_contract_service.py](/tests/test_contract_service.py)
- Arquivo: [test_conversations_memory_i18n.py](/tests/test_conversations_memory_i18n.py)
- Arquivo: [test_decompose_loop.py](/tests/test_decompose_loop.py)
- Arquivo: [test_decomposition.py](/tests/test_decomposition.py)
- Arquivo: [test_dev_tools.py](/tests/test_dev_tools.py)
- Arquivo: [test_diff_resume_browser.py](/tests/test_diff_resume_browser.py)
- Arquivo: [test_e2e_orchestrator.py](/tests/test_e2e_orchestrator.py)
- Arquivo: [test_end_to_end_requirements.py](/tests/test_end_to_end_requirements.py)
- Arquivo: [test_evolution_api.py](/tests/test_evolution_api.py)
- Arquivo: [test_failures.py](/tests/test_failures.py)
- Arquivo: [test_functional_depth.py](/tests/test_functional_depth.py)
- Arquivo: [test_global_acceptance.py](/tests/test_global_acceptance.py)
- Arquivo: [test_global_verify.py](/tests/test_global_verify.py)
- Arquivo: [test_guides_and_closing.py](/tests/test_guides_and_closing.py)
- Arquivo: [test_hierarchical_decompose.py](/tests/test_hierarchical_decompose.py)
- Arquivo: [test_home_branches.py](/tests/test_home_branches.py)
- Arquivo: [test_independent_verification.py](/tests/test_independent_verification.py)
- Arquivo: [test_knowledge_graph.py](/tests/test_knowledge_graph.py)
- Arquivo: [test_knowledge_imports.py](/tests/test_knowledge_imports.py)
- Arquivo: [test_llamacpp_provider.py](/tests/test_llamacpp_provider.py)
- Arquivo: [test_loose_memory_replan.py](/tests/test_loose_memory_replan.py)
- Arquivo: [test_mcp_manager.py](/tests/test_mcp_manager.py)
- Arquivo: [test_model_choice.py](/tests/test_model_choice.py)
- Arquivo: [test_observability_api.py](/tests/test_observability_api.py)
- Arquivo: [test_observability_e2e.py](/tests/test_observability_e2e.py)
- Arquivo: [test_observability_events.py](/tests/test_observability_events.py)
- Arquivo: [test_observability_executor.py](/tests/test_observability_executor.py)
- Arquivo: [test_observability_streaming.py](/tests/test_observability_streaming.py)
- Arquivo: [test_observability_unit1.py](/tests/test_observability_unit1.py)
- Arquivo: [test_operation_context.py](/tests/test_operation_context.py)
- Arquivo: [test_orchestrator_recovery.py](/tests/test_orchestrator_recovery.py)
- Arquivo: [test_persistence.py](/tests/test_persistence.py)
- Arquivo: [test_plan_validation.py](/tests/test_plan_validation.py)
- Arquivo: [test_progress_metrics.py](/tests/test_progress_metrics.py)
- Arquivo: [test_proportional_verification.py](/tests/test_proportional_verification.py)
- Arquivo: [test_requirements.py](/tests/test_requirements.py)
- Arquivo: [test_resume.py](/tests/test_resume.py)
- Arquivo: [test_resume_integrity.py](/tests/test_resume_integrity.py)
- Arquivo: [test_retry_strategy.py](/tests/test_retry_strategy.py)
- Arquivo: [test_run_termination.py](/tests/test_run_termination.py)
- Arquivo: [test_skills_catalog.py](/tests/test_skills_catalog.py)
- Arquivo: [test_skills_evaluation.py](/tests/test_skills_evaluation.py)
- Arquivo: [test_skills_observability.py](/tests/test_skills_observability.py)
- Arquivo: [test_skills_system.py](/tests/test_skills_system.py)
- Arquivo: [test_resolution_strategy.py](/tests/test_resolution_strategy.py)
- Arquivo: [test_stagnation_limits.py](/tests/test_stagnation_limits.py)
- Arquivo: [test_state_machine.py](/tests/test_state_machine.py)
- Arquivo: [test_strategy_and_decomposition.py](/tests/test_strategy_and_decomposition.py)
- Arquivo: [test_sufficient_context.py](/tests/test_sufficient_context.py)
- Arquivo: [test_tools.py](/tests/test_tools.py)

### `tests/test_browser_actions.py`

**Propósito:** verificar as ações de página (preencher, capturar, ária, console e rede) com uma página falsa.

### `tests/test_desktop_accessibility.py`

**Propósito:** verificar a leitura da árvore de acessibilidade e a recusa de clique sem nome ou sem geometria.

### `tests/test_tool_arguments.py`

**Propósito:** verificar a validação de argumentos no registro, antes de o handler rodar.

### `tests/test_language_strategy.py`

**Propósito:** verificar a escolha entre idioma original e inglês operacional, a fidelidade de literais e restrições, a herança do contrato e a troca única depois de saída inválida.

### `tests/test_quality_disposition.py`

**Propósito:** verificar contrato de qualidade, disposição da etapa, redação da explicação e a gravação desses fatos no ciclo do orquestrador.

### `tests/web/tools-report.test.mjs`

**Propósito:** verificar o resumo da aba Ferramentas a partir de respostas sintéticas da API.

### `tests/web/work-explained.test.mjs`

**Propósito:** verificar que `describeActivity` mostra o texto de `work.explained`, ignora evento sem texto e que `integrateNarrative` acopla a narração ao item operacional seguinte dentro do feed (sem lista separada no topo).

### `tests/web/narrative-replay.test.mjs`

**Propósito:** regressão com fixture real de `/observe` — todo texto de `work.explained` aparece acoplado às linhas do feed, sem entradas narrativas soltas.

### `tests/web/fixtures/observe-with-narration.json`

**Propósito:** snapshot persistido de uma run com eventos `work.explained` (entrada do teste `narrative-replay.test.mjs`).

### `tests/test_capability_exposure.py`

**Propósito:** verificar a exposição de capacidades: quais ferramentas o modelo recebe e como o prompt as resume.. camada de testes — comportamento do catálogo de ferramentas e do resumo de capacidades.
### `tests/test_desktop_automation.py`

**Propósito:** verificar a automação de desktop: adaptadores por plataforma, tela, entrada e janelas.. camada de testes — comportamento observável da camada de desktop no sistema atual.
### `tests/test_engineering_tools.py`

**Propósito:** verificar a caixa de ferramentas de engenharia: descoberta de projeto, Git e verificações.. camada de testes — comportamento da descoberta, do Git e do resumo de resultados.
### `tests/test_real_workflow_integration.py`

**Propósito:** demonstrar, com execução real, os fluxos de abrir aplicativo, manter software e usar skill.. camada de testes — integração do agente com o sistema, o projeto e o ciclo de vida das skills.
### `tests/test_skills_authoring.py`

**Propósito:** verificar o ciclo de vida das skills autorais: criação, validação, teste, ativação, versão e rollback.. camada de testes — comportamento do repositório de skills e do serviço de autoria.
### `tests/test_system_automation.py`

**Propósito:** verificar a automação do sistema: processos, tarefas em segundo plano, arquivos e rede.. camada de testes — comportamento real dos adaptadores de sistema sobre processos descartáveis.
### `tests/test_tool_contracts.py`

**Propósito:** verificar o contrato unificado das ferramentas: risco, permissões, disponibilidade, prazo e cancelamento.. camada de testes — comportamento do registro, da política e da sondagem de requisitos.
## `tests/fixtures/`

**Propósito:** Fixtures de teste (projeto de exemplo para o fluxo E2E).

## `tests/web/`

**Propósito:** Testes Node da interface (redutor ao vivo, feed, scroll, replay SSE).

- Subpasta: [fixtures/](/tests/web/fixtures/)
- Arquivo: [observe-core.test.mjs](/tests/web/observe-core.test.mjs)
- Arquivo: [observe-stream.test.mjs](/tests/web/observe-stream.test.mjs)
- Arquivo: [narrative-replay.test.mjs](/tests/web/narrative-replay.test.mjs)
- Arquivo: [work-explained.test.mjs](/tests/web/work-explained.test.mjs)
- Arquivo: [chat-scroll.test.mjs](/tests/web/chat-scroll.test.mjs)
- Arquivo: [replay.mjs](/tests/web/replay.mjs)
- Arquivo: [tools-report.test.mjs](/tests/web/tools-report.test.mjs)

## `tests/web/fixtures/`

**Propósito:** Snapshots JSON para testes offline do feed e da observabilidade.

- Arquivo: [observe-with-narration.json](/tests/web/fixtures/observe-with-narration.json)

### `tests/test_automation_chat_execution.py`

**Propósito:** Verificar que a automação criada pelo chat realmente dispara, de uma vez só, e sobrevive ao reinício.


### `tests/test_automation_chat_flow.py`

**Propósito:** Verificar o caminho completo do chat: pedido em linguagem natural, ferramentas, estado persistido e resposta.


### `tests/test_automation_chat_tools.py`

**Propósito:** Verificar as ferramentas de automação oferecidas ao chat e o serviço que elas chamam.


### `tests/test_automation_natural.py`

**Propósito:** Verificar a interpretação de horários em linguagem natural e a detecção de intenção de automação.


### `tests/web/observe-core.test.mjs`

**Propósito:** Teste Playwright do core de observabilidade (aplicação de eventos, árvore, métricas).

### `tests/web/observe-stream.test.mjs`

**Propósito:** Teste Playwright de streaming SSE (conexão, delta batching, reconexão).

### `tests/web/replay.mjs`

**Propósito:** Teste Playwright de replay de eventos (snapshot → replay → estado final).

### `tests/README.md`

**Propósito:** Índice da pasta `tests/` — organização, fixtures, como rodar.

### `tests/test_api.py`

**Propósito:** Testes de integração da API (FastAPI TestClient): CRUD projects/conversations/tasks/runs, observabilidade, fs_browse.

### `tests/test_atomizer.py`

**Propósito:** Testes do atomizer (micro-decomposição de operações complexas).

### `tests/test_attachments.py`

**Propósito:** Testes de materialização de anexos (imagens/docs).

### `tests/test_attempt_loop.py`

**Propósito:** Testes do loop de tentativas (dedup, fingerprint, exaustão).

### `tests/test_consolidation.py`

**Propósito:** Testes de consolidação de tarefas pai (evidências, verificação, status).

### `tests/test_context_budget.py`

**Propósito:** Testes do orçamento de tokens (ContextBudget, assemble_messages, truncagem).

### `tests/test_context_recovery.py`

**Propósito:** Testes de recuperação de contexto (snapshots, retomada).

### `tests/test_contract_impact.py`

**Propósito:** Testes de impacto de contrato (arquivos afetados → tasks impactadas).

### `tests/test_contract_service.py`

**Propósito:** Testes do ContractService (upsert, validação, impacto).

### `tests/test_conversations_memory_i18n.py`

**Propósito:** Testes integrados: conversas, memória, i18n (detecção de idioma).

### `tests/test_decompose_loop.py`

**Propósito:** Testes do loop de decomposição (plano → sub-tasks → execução).

### `tests/test_decomposition.py`

**Propósito:** Testes da decomposição (modelo, builtin, page, fallback, direct_answer).

### `tests/test_dev_tools.py`

**Propósito:** Testes de ferramentas de desenvolvimento (grep, git, system_info).

### `tests/test_diff_resume_browser.py`

**Propósito:** Testes de diff + retomada + browser.

### `tests/test_e2e_orchestrator.py`

**Propósito:** Testes E2E do orquestrador completo (run até idle, verificação, consolidação).

### `tests/test_end_to_end_requirements.py`

**Propósito:** Testes E2E de requisitos (derivação, cobertura, aceite global).

### `tests/test_evolution_api.py`

**Propósito:** Testes de evolução da API (compatibilidade, migrações).

### `tests/test_failures.py`

**Propósito:** Testes de classificação de falhas (domain/failures.py).

### `tests/test_functional_depth.py`

**Propósito:** Testes de profundidade funcional (múltiplos níveis de decomposição).

### `tests/test_global_acceptance.py`

**Propósito:** Testes de aceite global (todos requisitos satisfied → COMPLETED).

### `tests/test_global_verify.py`

**Propósito:** Testes de verificação global (reabertura de gaps, correção).

### `tests/test_guides_and_closing.py`

**Propósito:** Testes de descoberta de guias + stages de fechamento.

### `tests/test_hierarchical_decompose.py`

**Propósito:** Testes de decomposição hierárquica (task → sub-tasks → sub-sub-tasks).

### `tests/test_home_branches.py`

**Propósito:** Testes de branches na conversa "home" (inbox).

### `tests/test_independent_verification.py`

**Propósito:** Testes de verificação independente (quem executa não aprova).

### `tests/test_knowledge_graph.py`

**Propósito:** Testes do Knowledge Graph (indexação, busca, vizinhança).

### `tests/test_knowledge_imports.py`

**Propósito:** Testes de imports do KG (resolução de símbolos).

### `tests/test_llamacpp_provider.py`

**Propósito:** Testes do provider llama.cpp.

### `tests/test_loose_memory_replan.py`

**Propósito:** Testes de memória solta + replanejamento.

### `tests/test_mcp_manager.py`

**Propósito:** Testes do MCP Manager (descoberta, chamada, reload).

### `tests/test_model_choice.py`

**Propósito:** Testes de escolha de modelo (perfil, provider, reasoning).

### `tests/test_observability_api.py`

**Propósito:** Testes da API de observabilidade (eventos, snapshot, live).

### `tests/test_observability_e2e.py`

**Propósito:** Testes E2E de observabilidade (streaming, snapshot, live, replay).

### `tests/test_observability_events.py`

**Propósito:** Testes de emissão/eventos de observabilidade (EventBus, emitter).

### `tests/test_observability_executor.py`

**Propósito:** Testes do executor com observabilidade (streaming, operations live).

### `tests/test_observability_streaming.py`

**Propósito:** Testes de streaming real (SSE, DeltaBatcher, observed_chat).

### `tests/test_observability_unit1.py`

**Propósito:** Testes unitários de observabilidade (EventBus, emitter, batching, contracts).

### `tests/test_operation_context.py`

**Propósito:** Testes do OperationContextBuilder (componentes, prioridades, truncagem).

### `tests/test_orchestrator_recovery.py`

**Propósito:** Testes de recuperação do orquestrador (retomada, pause/resume, cancel).

### `tests/test_persistence.py`

**Propósito:** Testes de persistência (models, relationships, migrações SQLite).

### `tests/test_plan_validation.py`

**Propósito:** Testes de validação de plano (16 regras, repair, fingerprint).

### `tests/test_progress_metrics.py`

**Propósito:** Testes de métricas de progresso (verified/pending/blocked, made_progress).

### `tests/test_proportional_verification.py`

**Propósito:** Testes de verificação proporcional ao risco (tipo de verificação por kind).

### `tests/test_requirements.py`

**Propósito:** Testes de requisitos (derivação, covers, status).

### `tests/test_resume.py`

**Propósito:** Testes de resumo de run (onde parou, próximas ações).

### `tests/test_resume_integrity.py`

**Propósito:** Testes de integridade do resume.md (check/carimbar).

### `tests/test_retry_strategy.py`

**Propósito:** Testes de estratégia de retry (backoff, max_attempts, dedup).

### `tests/test_run_termination.py`

**Propósito:** Testes de terminação de run (completed, cancelled, failed, limits).

### `tests/test_skills_catalog.py`

**Propósito:** Testes do catálogo de Skills em Markdown (frontmatter, seções, precedência catálogo → projeto, skill inválida).

### `tests/test_skills_evaluation.py`

**Propósito:** Avaliação comparativa: tarefa simples vs. multinível, falha de skill, falha opcional vs. obrigatória, esgotamento de orçamento e ciclo de recuperação da verificação.

### `tests/test_skills_observability.py`

**Propósito:** Testes de integração dos eventos de estratégia, skills selecionadas, decomposição recursiva e recuperação da verificação.

### `tests/test_skills_system.py`

**Propósito:** Testes do sistema de Skills (descoberta, validação, seleção sob demanda).

### `tests/test_resolution_strategy.py`

**Propósito:** verificar a estratégia de resolução — repetição improdutiva, repetição legítima, mudança de abordagem, falha transitória, retomada, falha de subtarefa, falsa conclusão, evidência nova e coerência dos limites. **Quando/onde:** testes determinísticos da memória de abordagem e do contador de problema, sem dependência de modelo.

### `tests/test_stagnation_limits.py`

**Propósito:** Testes de detecção de estagnação + limites operacionais.

### `tests/test_state_machine.py`

**Propósito:** Testes da máquina de estados (transições válidas/inválidas).

### `tests/test_strategy_and_decomposition.py`

**Propósito:** Testes da camada estratégica, decomposição adaptativa e integridade.

### `tests/test_sufficient_context.py`

**Propósito:** Testes de contexto suficiente (budget, compactação, fallback).

### `tests/test_tools.py`

**Propósito:** Testes do registro de ferramentas + builtins (execução, aprovação, timeout, aliases).

## `web/`

**Propósito:** SPA estática servida pela API.

- Subpasta: [web/static/](/web/static/)
- Arquivo: [README.md](/web/README.md)

## `web/static/`

**Propósito:** Shell HTML da interface.

- Subpasta: [web/static/assets/](/web/static/assets/)
- Arquivo: [index.html](/web/static/index.html)

## `web/static/assets/`

**Propósito:** JS e CSS da interface (chat, árvore de tarefas, diff, observabilidade).

- Arquivo: [app.js](/web/static/assets/app.js)
- Arquivo: [observe-core.js](/web/static/assets/observe-core.js)
- Arquivo: [observe-view.js](/web/static/assets/observe-view.js)
- Arquivo: [observe.js](/web/static/assets/observe.js)
- Arquivo: [style.css](/web/static/assets/style.css)

### `web/static/assets/app.js`

**Propósito:** Módulo ES da interface principal: chat com o agente, projetos e conversas, árvore de tarefas, execução de runs e integração com o painel de observação. **Quando/onde:** é importado como módulo pela página principal servida em `web/static/`, sendo o ponto de entrada da UI (chama `init()` ao final do arquivo).

- `addAttachment(item)` — empilha um anexo (texto, imagem ou arquivo em base64) na lista local de anexos e repinta os chips. Quando o usuário anexa um arquivo por input, arrastar-soltar ou colagem.
- `agentBusy()` — informa se há envio pendente ou run em andamento, o que bloqueia novos envios. Quando o compositor e os botões verificam a ocupação do agente.
- `answerHtml(root)` — monta o HTML da resposta final da tarefa raiz: markdown visível, diffs de arquivos, referências e medidores. Quando o chat renderiza a bolha do agente.
- `api(path, opts = {})` — wrapper de `fetch` com cabeçalho JSON que lança `Error` com o texto do corpo quando a resposta não é OK. Quando qualquer trecho da UI fala com a API local.
- `appendChat(list, conversation, onOpen)` — cria a linha de uma conversa (botão com ícone, título e carimbo) e o menu de ações, chamando `onOpen` no clique. Quando a lista de conversas do projeto ou avulsa é montada.
- `applyConversation(updated)` — substitui a conversa em `state.loose`/`state.conversations` e, se for a atual, atualiza título e branch ativa. Quando a API devolve a conversa modificada.
- `beginRename()` — troca o `<h1>` do workspace por um input, salva o novo título via PATCH e restaura o cabeçalho. Quando o usuário aciona o botão de renomear conversa.
- `beginRenameProject(project)` — faz o mesmo com o nome do projeto, atualizando `state.projects` e o projeto selecionado. Quando o usuário renomeia o projeto pela barra lateral.
- `buildTreeNodes(tasks, parentId = null, depth = 0)` — achata a hierarquia de tarefas em lista linear, aplicando o filtro de status escolhido. Quando a árvore de tarefas é desenhada.
- `cancelRun()` — cancela a run atual via API, zera `currentRun`, para o polling e avisa o usuário. Quando o botão de parar/cancelar é acionado.
- `changesHtml(root)` — gera o HTML da lista de arquivos alterados, com contagem de linhas e diff expansível. Quando a resposta final exibe o que mudou nos arquivos.
- `chatCopy()` — devolve o dicionário de textos da UI no idioma vigente (pt/en/es). Quando balões, empty states e mensagens são montados.
- `chatMenu(conversation)` — cria o menu "⋮" com mover, renomear, alterar pasta e remover, já com os handlers ligados. Quando uma linha de conversa é inserida na lista.
- `collectChanges(root)` — percorre as descendentes da raiz e reúne as alterações de arquivo sem duplicar caminho. Quando se monta o diff consolidado da execução.
- `continueResume(taskId)` — aplica o resumo de retomada e reativa a run ou relança a execução da tarefa. Quando o usuário clica em "Continuar" no bloco de resume.
- `currentRoot()` — devolve a tarefa raiz (sem `parent_id`) da conversa atual, priorizando a selecionada. Quando se precisa do objetivo principal em execução.
- `descendantIds(rootId)` — coleta os ids de todas as descendentes da tarefa informada. Quando se filtra por subárvore (medidores, mudanças, pensamentos).
- `diffHtml(diff)` — converte um diff unificado em linhas HTML com classes `add`, `del` e `ctx`. Quando um diff de arquivo é exibido.
- `escapeHtml(s)` — escapa `&`, `<` e `>` para interpolação segura em HTML. Quando texto vindo do modelo ou do servidor entra no DOM.
- `eventLabel(ev)` — traduz um evento de atividade para um rótulo legível em português. Quando o feed de atividade é pintado.
- `fileChangeFrom(result)` — extrai `{path, added, removed, diff}` do resultado consolidado de uma tarefa, ignorando diffs internos. Quando se detectam arquivos alterados por uma etapa.
- `fileToAttachment(file)` — lê um `File` (texto como string, imagem/binário como base64) e o converte em item de anexo. Quando o usuário anexa arquivos pelo seletor, drag-and-drop ou colagem.
- `formatSpan(ms)` — formata milissegundos como `m:ss` ou `h:mm:ss`. Quando se exibe a duração de uma execução.
- `formatTime(iso)` — alias de `formatWhen` que devolve a hora formatada do carimbo ISO. Quando se mostra apenas o horário de um evento.
- `formatTokens(value)` — formata a contagem de tokens (número cru ou `1,2k`). Quando se mostra o consumo de tokens.
- `formatWhen(iso)` — converte um carimbo ISO em hora local (data + hora quando for outro dia). Quando se mostra quando algo aconteceu.
- `icon(name)` — devolve o SVG inline do ícone pedido, com fallback `circle`. Quando qualquer botão ou badge precisa de um ícone.
- `init()` — inicializa a UI: ícones, abas, eventos do chat, modelos, projetos, anexos, atalhos de teclado e ações de run. Quando o módulo é carregado (executado no fim do arquivo).
- `keepComposerChoices(form)` — reseta o formulário preservando o provider e o modelo selecionados. Quando uma mensagem é enviada, para não perder as escolhas.
- `latestRunId()` — devolve o id da run atual ou da última run vinculada à tarefa raiz. Quando o painel de observação precisa se abrir.
- `linkifyText(html)` — transforma URLs em texto puro em links, preservando as tags HTML existentes. Quando o texto renderizado contém endereços.
- `loadFolder(path)` — lista o conteúdo de um diretório via `/fs/browse` e monta as entradas do modal de pasta. Quando o seletor de pasta navega entre diretórios.
- `loadInspector(taskId)` — busca a tarefa, tentativas, evidências, snapshots de contexto e contrato, preenchendo o painel de detalhe. Quando uma tarefa é selecionada na árvore.
- `loadModels()` — popula o seletor de modelos do provider atual, com opção de fallback quando o provider está offline. Quando o provider muda ou a página carrega.
- `loadPrefs()` — lê as preferências da UI do `localStorage`, tolerando JSON inválido. Quando se recupera o estado anterior (projeto, conversa, modelo).
- `meterParts(startIso, endIso, tokens, live)` — calcula duração e tokens de um intervalo, usando o instante atual quando o medidor está "live". Quando se monta um medidor de tempo.
- `meterTag(startIso, endIso, tokens, live)` — gera a tag `<time class="meter">` com ícone de timer, duração e tokens. Quando se exibe o tempo de uma tarefa ou de uma run.
- `moveConversation(conversation, projectId)` — move a conversa para outro projeto (ou tira do projeto) e reatualiza listas e seleção. Quando o menu da conversa escolhe um destino.
- `observePanel()` — devolve o elemento do painel de observação. Quando se verifica se o painel existe e está visível.
- `openFolderPicker(start)` — abre o modal de escolha de pasta e carrega o diretório inicial. Quando o usuário quer trocar a pasta do projeto ou da conversa.
- `paintBranches()` — atualiza o indicador de branch (`n/total`) do workspace. Quando a conversa tem duas ou mais branches.
- `paintBrowser()` — atualiza o chip do modo de navegador (desligado, invisível ou janela). Quando o modo muda ou a página carrega.
- `paintComposer()` — ajusta ícone, rótulo e estado do botão de envio conforme o agente estar ocupado. Quando o estado da execução muda.
- `paintIcons(root = document)` — insere os SVGs nos elementos com `data-icon` que ainda não têm `<svg>`. Quando HTML novo é renderizado na tela.
- `paintWorkspace()` — atualiza título, subtítulo e caminho da conversa ou projeto no cabeçalho. Quando a conversa ou o projeto selecionado muda.
- `parseStamp(iso)` — converte carimbo ISO do servidor (UTC) em `Date`, assumindo UTC quando não há fuso explícito. Quando se interpreta `created_at`/`updated_at`.
- `pendingBubble()` — monta a bolha de "enviando" com o texto e os anexos enquanto a tarefa ainda não aparece. Quando um envio está em voo.
- `referenceLinks(markdown, root)` — extrai URLs do markdown e das `sources` do relatório consolidado. Quando se monta a lista de referências.
- `refreshActivity()` — busca os eventos do workspace e pinta o feed de atividade com os 40 mais recentes. Quando se atualiza a visão geral do projeto.
- `refreshAll()` — roda em paralelo a atualização de tarefas, overview, atividade e estado live, e repinta o chat. Quando se quer sincronizar a interface inteira.
- `refreshConversationList()` — recarrega as conversas do projeto (ou as avulsas) preservando a selecionada. Quando uma conversa é criada ou alterada.
- `refreshLive()` — busca o estado "live" do workspace, atualiza a barra de status e liga ou desliga o polling. Enquanto há execução em andamento.
- `refreshOverview()` — busca o overview do projeto e atualiza os chips de status na barra de estatísticas. Quando se exibe o resumo quantitativo.
- `refreshTasks()` — recarrega as tarefas da conversa (filtradas pela branch) ou do workspace e repinta árvore e chat. Quando a conversa muda ou o polling roda.
- `refsHtml(markdown, root)` — gera o bloco HTML com os links de referência da resposta. Quando a resposta final tem fontes.
- `removeConversation(conversation)` — apaga a conversa via DELETE e limpa o estado, as listas e o chat. Quando o menu escolhe "Remover".
- `renderAttachmentChips()` — repinta os chips dos anexos pendentes na linha de anexos. Quando um anexo é adicionado ou removido.
- `renderChat()` — redesenha o log inteiro do chat: bolhas do usuário e do agente, cards de ferramentas, mediações e respostas. Quando o estado de tarefas ou de execução muda.
- `renderDiagram(source)` — converte um diagrama Mermaid simples (nós `id[label]` e setas `-->`) em SVG. Quando o markdown traz um bloco `mermaid`.
- `renderInline(text)` — aplica a formatação inline do markdown (código, negrito, links e referências a arquivos). Quando o conteúdo inline de um bloco é renderizado.
- `renderLive(live)` — atualiza os ícones de ação, modelo e ferramenta da barra de status. Quando o snapshot "live" do servidor muda.
- `renderLoose()` — repinta a lista de conversas fora de projeto. Quando `renderProjects` é chamado.
- `renderMarkdown(raw)` — converte markdown em HTML, tratando blocos de código e diagramas Mermaid. Quando a resposta do modelo é exibida.
- `renderMarkdownBlocks(chunk)` — converte um trecho de markdown sem blocos de código em HTML (títulos, listas, tabelas e parágrafos). Quando `renderMarkdown` processa as partes de texto.
- `renderProjects(filter = "")` — repinta a barra lateral com os projetos filtrados, as conversas aninhadas e as ações de cada um. Quando a busca de projetos muda ou a lista é recarregada.
- `renderTaskTree()` — desenha a árvore de tarefas com status, seleção e marca de "busy", selecionando a raiz quando nada está selecionado. Quando as tarefas são recarregadas.
- `reopenObserver()` — reabre o painel de observação para a run mais recente da conversa. Quando a conversa muda ou o painel é reaberto.
- `resultLine(task)` — extrai uma linha resumida do resultado consolidado (erro, resumo ou stdout). Quando o detalhe de uma etapa é exibido.
- `resumeHtml(root)` — gera o bloco de retomada com o que foi feito, o que falta, o motivo e o botão "Continuar". Quando existe um `resumeBrief` para a tarefa raiz.
- `runConfigFromUI(objective)` — monta a configuração da run (provider, modelo, aprovação de ferramentas, modo de browser) a partir dos controles da UI. Quando o usuário envia um objetivo ou inicia uma run.
- `runMeter(root)` — monta o medidor agregado de tempo e tokens de uma run, somando as descendentes. Quando a bolha do agente mostra o custo da execução.
- `sameTitleCount(task)` — conta as descendentes com o mesmo título, sinalizando etapas duplicadas. Quando o card de uma ferramenta é renderizado.
- `savePrefs(partial)` — mescla e grava as preferências da UI no `localStorage`. Quando qualquer escolha persistível é alterada.
- `selectConversation(conversation)` — troca a conversa ativa, limpa seleções, salva a preferência e recarrega tarefas e estado live. Quando o usuário abre uma conversa.
- `selectLoose(conversation)` — seleciona uma conversa fora de projeto, escondendo a barra de execução. Quando o usuário abre um chat avulso.
- `selectProject(p)` — seleciona o projeto, carrega suas conversas, restaura a última usada e atualiza a interface. Quando o usuário clica em um projeto na barra lateral.
- `selectTask(taskId)` — marca a tarefa como selecionada, repinta a árvore e carrega o inspetor. Quando o usuário clica em uma tarefa.
- `setupTabs()` — liga o clique das abas à troca do painel ativo. Quando a página carrega.
- `shiftBranch(delta)` — ativa a branch anterior ou seguinte da conversa e recarrega as tarefas dela. Quando o usuário navega entre branches.
- `stageDetail(task)` — monta o detalhe de uma etapa (caminho, contagem de linhas, diff e resumo do resultado). Quando um card de ferramenta é expandido.
- `stageMeter(task)` — medidor de tempo e tokens de uma tarefa, considerado "live" enquanto ela está em execução. Quando um card de etapa é renderizado.
- `stageMetersHtml(root)` — linha com os medidores de tempo de cada subtarefa da raiz. Quando a resposta final é exibida.
- `stampTag(iso)` — gera a tag `<time class="stamp">` com ícone de relógio e hora. Quando se marca quando algo aconteceu.
- `startConversation()` — cria uma conversa no projeto selecionado (ou avulsa, se não houver projeto) e a abre. Quando o usuário clica em "Nova conversa".
- `startLooseConversation()` — cria uma conversa sem projeto, na pasta do usuário, e a abre. Quando o usuário inicia um chat avulso.
- `startPolling()` — inicia o intervalo de 2,5 s que reatualiza a tela enquanto houver run ativa. Quando a polling está habilitada e existe execução.
- `startRun(config, { onStarted } = {})` — cria a run, habilita o modo autônomo, dá o primeiro passo e dispara o polling. Quando o usuário executa o objetivo.
- `statusBadge(status)` — gera a badge de status com o ícone correspondente. Quando o status de uma tarefa ou run é exibido.
- `stopPolling()` — cancela o timer de polling. Quando a run termina, é pausada ou cancelada.
- `syncObserver()` — reabre o observador quando o id da run atual mudou. Quando o snapshot live aponta outra execução.
- `taskTokens(task)` — devolve os tokens consumidos pela tarefa, lendo `usage_tokens` ou os metadados. Quando se calcula o custo de uma etapa.
- `thoughtBlock(root)` — monta o bloco expansível com os pensamentos do agente na subárvore da raiz. Enquanto a execução está pensando e ainda não há resposta.
- `tickMeters()` — atualiza a cada segundo a duração dos medidores marcados como "live". Quando há tarefas em execução.
- `titleOf(task)` — devolve o título exibível da tarefa (`display_title` ou `title`). Quando um card ou nó da árvore é rotulado.
- `toast(message, type = "info")` — exibe uma notificação temporária no canto da tela. Quando uma operação avisa sucesso ou erro.
- `toggleObserver()` — mostra ou esconde o painel de observação, criando o observer na primeira abertura. Quando o botão "observar" é acionado.
- `toolOf(task)` — deduz a ferramenta usada pela tarefa a partir dos metadados (tool, verificação ou modelo). Quando se escolhe o ícone de uma etapa.
- `uiLocale()` — decide o idioma da UI (da conversa, do navegador ou pt como padrão). Quando se busca os textos do chat.
- `updateRunButtons()` — habilita ou desabilita os botões de executar, passo, pausa e cancelar conforme o estado atual. Quando o estado da execução muda.
- `useFolder(path)` — aplica a pasta escolhida ao projeto ou à conversa alvo e fecha o modal. Quando o usuário confirma a seleção de pasta.
- `visibleReply(markdown)` — extrai a parte visível da resposta (seção "resposta final", lista de arquivos ou linha "Agora:"). Quando se decide o que mostrar ao usuário.
- `workspaceId()` — devolve o id do workspace (projeto selecionado ou o da conversa). Quando se chama uma API escopada por projeto.

### `web/static/assets/observe-core.js`

**Propósito:** Estado puro (sem DOM) da tela de acompanhamento de uma run, alimentado pela foto do servidor (`/runs/{id}/observe`) e pelos envelopes do SSE (`/runs/{id}/stream`). **Quando/onde:** é importado por `observe.js` e `observe-view.js` para agregar e filtrar o que o navegador exibe, sem decidir o estado real das tarefas.

- `applyEvent(state, env, { replay = false, now = Date.now()` — aplica um envelope ao estado, deduplicando por `seq` e descartando fragmentos atrasados; devolve `false` quando o envelope foi ignorado. Quando chega um evento do SSE ou do replay do snapshot.
- `applyLive(state, live)` — sobrepõe outputs e operações com o snapshot "live" do servidor quando ele for mais recente. Quando o servidor emite o evento `live`.
- `buildTree(state)` — monta a árvore hierárquica das tarefas com `done/total` das folhas assentadas. Quando a árvore do painel é desenhada.
- `cap(list, max)` — corta o início da lista quando ela passa de `max` itens e devolve a própria lista. Quando se limitam eventos, saídas e histórico.
- `category(type)` — devolve a categoria (prefixo antes do ponto) de um tipo de evento. Quando se filtram ou rotulam eventos.
- `countsText(counts)` — formata um objeto de contagens (`{passed: 3}`) como texto legível. Quando se mostra o resultado de uma bateria de testes.
- `createState(snapshot, now = Date.now()` — cria o estado inicial a partir do snapshot do servidor, reaplicando os eventos e marcando as operações interrompidas. Quando o painel abre uma run.
- `criterionText(value)` — extrai o texto de um critério de verificação (string, descrição, comando ou JSON). Quando se registra uma verificação.
- `currentTask(state)` — devolve a tarefa em execução mais relevante segundo a ordem de status. Quando o cabeçalho mostra a tarefa atual.
- `describe(env)` — traduz um envelope em uma frase legível conforme o seu tipo. Quando os eventos são listados na atividade.
- `elapsedSeconds(state, now = Date.now()` — devolve o tempo decorrido da run, congelando o valor quando ela terminou ou está pausada. Quando o cabeçalho mostra a duração.
- `emptyMetrics()` — devolve o contador de métricas zerado (recebidos, persistidos, duplicados, latências e demais). Quando o estado é criado.
- `filesList(state, filters = {})` — devolve os eventos de arquivo dentro do escopo dos filtros. Quando a área de arquivos é pintada.
- `findLast(list, pred)` — percorre a lista de trás para frente devolvendo o último item que satisfaz o predicado. Quando se localiza uma verificação ainda aberta.
- `insertSorted(list, env)` — insere o envelope na lista mantendo a ordem crescente de `seq`. Quando eventos persistidos chegam fora de ordem.
- `latency(state)` — resume as amostras de atraso (média, máximo e última). Quando se mostra a latência do stream.
- `markConnection(state, connection)` — registra o estado da conexão e conta as reconexões. Quando o SSE muda de status.
- `markResync(state)` — incrementa o contador de ressincronizações. Quando o servidor pede um resync.
- `matches(state, item, filters = {}, scope = null)` — testa se um item satisfaz os filtros (tarefa, categorias, erros e texto). Quando se filtra a atividade.
- `newOp(kind, callId, taskId, seq)` — cria o registro de uma operação de tool, command ou test em execução. Quando chega o evento de início da operação.
- `newOutput(id, env)` — cria o registro de uma saída do modelo, com status inicial "waiting". Quando chega `agent.started`.
- `outputsList(state, filters = {})` — lista as saídas do modelo dentro do escopo, ordenadas por início. Quando a área de respostas do agente é pintada.
- `parseTs(iso)` — converte carimbo ISO do servidor (UTC) em `Date.parse`, assumindo UTC quando não há fuso explícito. Quando se calcula a latência de um envelope.
- `progressText(progress = {})` — formata o progresso do servidor ("N verificadas · N pendentes"). Quando o cabeçalho mostra o progresso da run.
- `recordLatency(state, env, now)` — registra a amostra de atraso entre o carimbo do evento e a chegada dele. Quando um envelope novo é aplicado.
- `reduce(state, env, { fresh, persisted })` — despacha o envelope para o redutor da sua categoria (run, task, agent, op, file, verification). Quando `applyEvent` processa um evento.
- `reduceAgent(state, env, d, persisted)` — atualiza a saída do modelo: status, deltas concatenados, conclusão ou falha. Quando chegam eventos `agent.*`.
- `reduceOp(state, env, d, kind, persisted)` — atualiza a operação de tool, command ou test (saída parcial, status, exit code, duração). Quando chegam os eventos dessas operações.
- `reduceRun(state, type, d, fresh)` — aplica status e modo da run (ativa, pausada, encerrada) e o progresso informado. Quando chegam eventos `run.*`.
- `reduceTask(state, env, d, fresh)` — cria ou atualiza a tarefa (status, título, motivo de bloqueio/falha, timestamps). Quando chegam eventos `task.*`.
- `scoped(state, filters, items)` — filtra os itens pelo escopo da tarefa selecionada, incluindo descendentes. Quando se aplica o filtro de tarefa.
- `sortTasks(a, b)` — ordena tarefas por `sort_order` e, em empate, pelo título. Quando a árvore é montada.
- `subtreeIds(state, rootId)` — coleta os ids da tarefa e de todas as suas descendentes. Quando se filtra por tarefa.
- `tailText(text, max)` — devolve apenas os últimos `max` caracteres do texto. Quando se limita o tamanho de saídas e terminais.
- `terminalList(state, filters = {})` — lista comandos e testes (e tools com saída) no escopo, ordenados por início. Quando a área de terminal é pintada.
- `toolList(state, filters = {})` — lista apenas as operações de ferramenta dentro do escopo. Quando a área de ferramentas é pintada.
- `trimOps(state)` — remove operações antigas e já finalizadas quando o mapa excede o limite. Quando o estado cresce demais.
- `trimOutputs(state)` — remove saídas finalizadas quando o mapa excede o limite. Quando o estado cresce demais.
- `verificationList(state, filters = {})` — junta verificações e testes como itens de verificação, ordenados por `seq`. Quando a área de verificação é pintada.
- `visibleEvents(state, filters = {}, limit = 300)` — devolve os eventos mais recentes que passam pelos filtros, até o limite informado. Quando a lista de atividade é montada.

### `web/static/assets/observe-view.js`

**Propósito:** Geração do HTML de cada área do painel de acompanhamento a partir do estado de `observe-core.js`. **Quando/onde:** é importado por `observe.js`, que chama cada renderizador por área; é puro, sem tocar no DOM.

- `clock(iso)` — formata um carimbo ISO como hora local `hh:mm:ss`. Quando se mostra a hora de um evento.
- `duration(seconds)` — formata segundos como `12s`, `3m20s` ou `1h05m`. Quando se mostra a duração da run.
- `esc(value)` — escapa `&`, `<`, `>`, `"` e `'` para uso seguro dentro de HTML. Quando o HTML do painel é montado.
- `renderActivity(state, filters, limit = 200)` — gera a lista HTML de eventos recentes, com hora, `seq`, descrição e referência da tarefa. Quando a aba "Atividade" é pintada.
- `renderFiles(state, filters, openSeqs)` — gera a lista de arquivos criados, alterados ou removidos, com o diff expansível. Quando a aba "Arquivos" é pintada.
- `renderFilters(state, filters)` — gera os chips de categoria, o modo "Só falhas", a tarefa selecionada e o campo de busca. Quando a barra de filtros é repintada.
- `renderHeader(state, now = Date.now()` — monta o cabeçalho com objetivo, status e modo da run, duração, progresso, tarefa atual, conexão e latência. Quando o painel é atualizado.
- `renderInterrupted(state)` — gera o aviso de operações interrompidas sem conclusão gravada. Quando o snapshot traz a lista `interrupted`.
- `renderMetrics(state)` — resume as métricas do stream (recebidos, persistidos, duplicados, reconexões, atraso). Quando a linha de métricas é pintada.
- `renderOutputs(state, filters)` — gera os cartões das chamadas ao modelo com status, metadados e o texto acumulado. Quando a aba "Respostas do agente" é pintada.
- `renderTaskHistory(state, taskId)` — gera a lista cronológica dos últimos eventos de uma tarefa. Quando há uma tarefa selecionada no filtro.
- `renderTerminal(state, filters)` — gera os cartões de comandos e testes com código de saída, duração e saída capturada. Quando a aba "Terminal" é pintada.
- `renderTools(state, filters)` — gera a lista das ferramentas chamadas com status e erro ou resumo. Quando a área de ferramentas é pintada.
- `renderTree(state, opts)` — monta o HTML da árvore de tarefas, respeitando nós expandidos, colapsados e a seleção. Quando a aba "Tarefas" é pintada.
- `renderVerification(state, filters)` — gera a lista de verificações e testes com veredito, verificador e resumo. Quando a aba "Verificação" é pintada.
- `statusBadge(status, interrupted = false)` — gera a badge de status da tarefa, tratando o caso interrompido. Quando um nó da árvore ou um item é rotulado.
- `summaryText(summary)` — achata um objeto de resumo em texto "chave valor · chave valor". Quando se mostra o resumo de uma ferramenta.
- `taskTitle(state, id)` — devolve o título da tarefa pelo id, ou string vazia. Quando se referencia uma tarefa em um item.
- `treeNode(state, node, opts)` — gera o HTML de um nó da árvore (status, título, progresso, tentativas, evidência) e recursa nos filhos. Quando `renderTree` percorre a árvore.

### `web/static/assets/observe.js`

**Propósito:** Controlador do painel de acompanhamento: busca a foto da run, assina o SSE e redesenha as áreas no máximo uma vez por quadro. **Quando/onde:** é importado por `app.js`, que o instancia em `toggleObserver()` para o painel `#observe-panel`.

- `close()` — invalida a geração atual, para o stream e o ticker, e limpa o estado e o `runId`. Quando o observador é fechado ou outra run é aberta.
- `createObserver({ root, fetchJson, EventSourceImpl = globalThis.EventSource, now = ()` — cria o controlador do painel: monta o layout, liga os eventos de clique e filtro e expõe `open`/`close` e o estado. Quando o painel de observação é instanciado.
- `createStream({ runId, cursor, EventSourceImpl, onEnvelope, onLive, onResync, onEnd, onStatus, timers = globalThis })` — assina o SSE da run, encaminhando envelopes, live, resync e end, e reconecta com espera crescente. Quando uma run é aberta.
- `finish(mine)` — encerra o stream, recarrega o snapshot final, preserva as métricas e marca a conexão como encerrada. Quando a run termina ou chega o evento `end`.
- `followBottom(name)` — rola até o fim os blocos `<pre>` de uma área. Quando chegam saídas novas ou saída de terminal.
- `layout()` — devolve o HTML do painel com cabeçalho, aviso de interrupção, filtros e as áreas expansíveis. Quando o observador é criado.
- `load(id, mine)` — busca o snapshot de `/runs/{id}/observe` e o descarta se a geração já mudou. Quando uma run é aberta ou finalizada.
- `open()` — abre a conexão SSE da run em `/runs/{id}/stream?after=<seq>`, ligando os handlers de open, message, live, resync, rotate, end e error. Quando `createStream` inicia a assinatura.
- `paint(name, html)` — escreve o HTML de uma área apenas quando o conteúdo mudou, devolvendo se houve alteração. Quando o painel é redesenhado.
- `paintFilters()` — força a repintura da barra de filtros, invalidando o cache da área. Quando os filtros mudam.
- `render()` — redesenha todas as áreas do painel a partir do estado atual. Quando um redesenho é agendado.
- `schedule()` — agenda um redesenho por quadro, no máximo um pendente por vez. Quando chegam eventos ou o usuário interage.
- `stop()` — encerra o stream SSE, cancela o timer de reconexão e descarta o `EventSource`. Quando a run termina ou o observador fecha.
- `stopStream()` — para o stream SSE ativo e o descarta. Quando o observador é fechado ou troca de run.
- `toggleCategory(cat)` — alterna uma categoria no filtro (conjunto vazio significa todas). Quando o usuário clica num chip de categoria.

### `web/static/assets/style.css`

**Propósito:** Estilos globais da SPA (tema, layout, componentes, observabilidade, dark mode).

### `web/static/index.html`

**Propósito:** Shell HTML da SPA (imports, mount point, meta tags, CSP).

### `web/README.md`

**Propósito:** Índice da pasta `web/` (SPA estática, build, assets).

### `src/agent/api/agent_routes.py`

**Propósito:** agent_routes — módulo do projeto.

- `AgentExecutionRead` — Representação pública de uma execução de agente, serializada para a interface.
- `list_agents(project_id, session) → list[AgentRead]` — Árvore de agentes do projeto (raízes primeiro).
- `get_agent(agent_id, session) → AgentRead` — Detalha um agente da hierarquia.
- `agent_executions(agent_id, session) → list[AgentExecutionRead]` — Lista o histórico de execuções de um agente.
- `suspend_agent(agent_id, reason, session) → dict` — Suspende a execução do agente: persiste o estado e libera o contexto.
- `resume_agent(agent_id, session) → dict` — Retoma a execução suspensa a partir do estado persistido.
- `discard_agent(agent_id, body, session) → dict` — Descarta o estado recuperável do agente. Resultados e artefatos são preservados.
- `agent_queries(agent_id, session) → list[AgentQueryRead]` — Lista as consultas dirigidas feitas a um agente.
- `ask_agent(agent_id, body, session, settings) → AgentQueryRead` — Consulta dirigida: o solicitante pergunta ao alvo e recebe a resposta.
- `resource_metrics(session, settings) → dict` — Métricas de recursos e de uso — só o que o Callidus sabe medir de fato.

- `_agent_read(service, agent) → AgentRead` — Converte um agente persistido na visão pública da interface.
- `_count_by(rows, attribute) → dict[str, int]` — Conta as linhas agrupadas pelo valor de um atributo.
### `src/agent/api/automation_routes.py`

**Propósito:** automation_routes — módulo do projeto.

- `AutomationIn` — Definição enviada pela interface.
- `AutomationPatch` — Mudanças parciais de uma automação existente.
- `TestIn` — Opções do teste controlado de uma automação.
- `validate_automation(body) → dict` — Valida a definição sem gravar nada.
- `create_automation(body, session) → dict` — Cria a automação. Ela nasce desabilitada, a menos que `activate` peça o contrário.
- `list_automations(project_id, state, session) → list[dict]` — Lista as automações visíveis, opcionalmente filtradas.
- `supervisor_status(settings) → dict` — Situação do runtime de automações.
- `supervisor_diagnose(settings) → dict` — Diagnóstico: automações, próximos disparos e disparos pendentes.
- `get_automation(automation_id, session) → dict` — Detalha uma automação com seus disparos recentes e eventos.
- `update_automation(automation_id, body, session) → dict` — Aplica mudanças parciais em uma automação.
- `delete_automation(automation_id, session) → dict` — Remove uma automação.
- `enable_automation(automation_id, session) → dict` — Reativa uma automação suspensa ou desabilitada.
- `suspend_automation(automation_id, session) → dict` — Suspende uma automação, pausando os disparos futuros.
- `disable_automation(automation_id, session) → dict` — Desabilita uma automação de forma permanente, até nova reativação.
- `list_firings(automation_id, limit, session) → list[dict]` — Lista os disparos de uma automação, do mais recente para o mais antigo.
- `run_now(automation_id, wait, session, settings) → dict` — Executa uma vez, agora. Cria um disparo manual (chave própria).
- `test_automation(automation_id, body, session, settings) → dict` — Verifica a prontidão e, com `execute`, dispara um teste controlado.
- `cancel_automation(automation_id, session) → dict` — Cancela os disparos pendentes da automação.

- `_present(session, row) → dict[str, Any]` — Serializa uma automação persistida no formato entregue à interface.
- `_present_firing(row) → dict[str, Any]` — Serializa um disparo de automação no formato entregue à interface.
- `_readable_errors(exc) → list[dict]` — Erros de validação legíveis (o `ctx` do pydantic carrega objetos não serializáveis).
- `_service(session) → AutomationService` — Cria o serviço de automações sobre a sessão da requisição.
- `_load(session, automation_id) → AutomationModel` — Carrega uma automação ou responde 404.
### `src/agent/api/provider_routes.py`

**Propósito:** provider_routes — módulo do projeto.

- `ProviderEntry` — Descrição de um provedor editável pela interface.
- `ProviderConfigIn` — Configuração de provedores enviada pela interface.
- `SecretIn` — Credencial de um provedor enviada pela interface.
- `read_provider_config(settings) → dict` — Configuração de provedores em uso (sem credenciais) e onde ela vive.
- `write_provider_config(payload, settings) → dict` — Grava a configuração de provedores. Valida tipos, URLs e nomes antes de escrever.
- `delete_provider(name, settings) → dict` — Remove um provedor da configuração (a credencial gravada vai junto).
- `set_provider_secret(name, payload, settings) → dict` — Grava a credencial do provedor em arquivo com permissão restrita e aponta a configuração.
- `clear_provider_secret(name, settings) → dict` — Apaga a credencial gravada e limpa a referência no arquivo de configuração.
- `test_provider(name, settings) → dict` — Testa a conexão com o provedor: lista os modelos, sem gastar inferência.

- `_catalog(settings) → ProviderCatalog` — Carrega o catálogo de provedores das configurações.
- `_config_payload(settings) → dict[str, Any]` — Monta o payload da configuração de provedores, sem credenciais.
### `src/agent/automation/__init__.py`

**Propósito:** __init__ — módulo do projeto.

### `src/agent/automation/actions/__init__.py`

**Propósito:** __init__ — módulo do projeto.

### `src/agent/automation/actions/base.py`

**Propósito:** base — módulo do projeto.

- `ActionContext` — Tudo o que a ação precisa, já resolvido.
- `ActionResult` — Desfecho de uma ação.
- `Action` — O mínimo que o runtime precisa de uma ação.
- `register_action(kind, factory) → None` — Registra (ou substitui) um tipo de ação.
- `action_factories() → dict[str, ActionFactory]` — Fábricas de ação registradas.
- `build_action(spec) → Action` — Instancia a ação de uma especificação.
- `execute(self, ctx) → ActionResult` — Executa a ação aprovada e devolve o resultado (saída, código de saída e erro).

- `Action.execute(self, ctx) → ActionResult` — Executa a ação aprovada e devolve o resultado (saída, código de saída e erro).
### `src/agent/automation/actions/callidus.py`

**Propósito:** callidus — módulo do projeto.

- `CallidusActionRunner` — Ação Callidus.
- `execute(self, ctx) → ActionResult` — Cria a tarefa raiz, inicia o run e o entrega ao worker autônomo.

- `_uuid_or_none(value) → uuid.UUID | None` — Converte um texto em UUID, tolerando ausência e valor inválido.
- `_resolve_objective(self, ctx) → str | None` — Objetivo da execução, conforme a política de versão.
- `_wait_for_run(self, ctx, run_id) → tuple[str, dict[str, Any]] | None` — Espera o run chegar a um estado terminal.

- `CallidusActionRunner.execute(self, ctx) → ActionResult` — Cria a tarefa raiz, inicia o run e o entrega ao worker autônomo.
- `CallidusActionRunner._resolve_objective(self, ctx) → str | None` — Objetivo da execução, conforme a política de versão.
- `CallidusActionRunner._wait_for_run(self, ctx, run_id) → tuple[str, dict[str, Any]] | None` — Espera o run chegar a um estado terminal.

- `CallidusActionRunner.__init__(self, spec) → None` — Cria a ação a partir da sua especificação.
### `src/agent/automation/actions/script.py`

**Propósito:** script — módulo do projeto.

- `ScriptActionRunner` — Ação de script.
- `execute(self, ctx) → ActionResult` — Valida as permissões e executa o script no destino configurado.

- `_remote_config(remote_cfg)` — Traduz a configuração do destino em `RemoteConfig` (o mesmo do projeto remoto).
- `_command(self) → list[str]` — Comando a executar, já com o interpretador quando informado.
- `_run_local(self, ctx, command, timeout, project_root) → ActionResult` — Executa o script na máquina local.
- `_run_remote(self, ctx, command, timeout) → ActionResult` — Executa o script no computador remoto do projeto.
- `_receipt_path(self, ctx, cwd) → Path | None` — Caminho do recibo da execução, quando a definição informa um.
- `_read_receipt(self, receipt) → str | None` — Conteúdo do recibo, quando existe.
- `_write_receipt(self, receipt, key) → None` — Grava o recibo da execução.
- `_safe_command(self) → list[str]` — Comando informado na definição, sem o interpretador acrescentado.

- `ScriptActionRunner._command(self) → list[str]` — Comando a executar, já com o interpretador quando informado.
- `ScriptActionRunner.execute(self, ctx) → ActionResult` — Valida as permissões e executa o script no destino configurado.
- `ScriptActionRunner._run_local(self, ctx, command, timeout, project_root) → ActionResult` — Executa o script na máquina local.
- `ScriptActionRunner._run_remote(self, ctx, command, timeout) → ActionResult` — Executa o script no computador remoto do projeto.
- `ScriptActionRunner._receipt_path(self, ctx, cwd) → Path | None` — Caminho do recibo da execução, quando a definição informa um.
- `ScriptActionRunner._read_receipt(self, receipt) → str | None` — Conteúdo do recibo, quando existe.
- `ScriptActionRunner._write_receipt(self, receipt, key) → None` — Grava o recibo da execução.
- `ScriptActionRunner._safe_command(self) → list[str]` — Comando informado na definição, sem o interpretador acrescentado.

- `ScriptActionRunner.__init__(self, spec) → None` — Cria a ação a partir da sua especificação.
### `src/agent/automation/cli.py`

**Propósito:** cli — módulo do projeto.

- `cmd_run(args) → int` — Roda o supervisor em primeiro plano.
- `cmd_install(args) → int` — Instala o serviço nativo do sistema operacional.
- `cmd_uninstall(args) → int` — Remove o serviço nativo.
- `cmd_start(args) → int` — Inicia o serviço nativo.
- `cmd_stop(args) → int` — Para o serviço nativo.
- `cmd_status(args) → int` — Mostra a situação do runtime e do serviço nativo.
- `cmd_diagnose(args) → int` — Mostra o diagnóstico detalhado do runtime.
- `cmd_list(args) → int` — Lista as automações registradas.
- `build_parser() → argparse.ArgumentParser` — Monta o interpretador de argumentos da linha de comando.
- `main(argv) → int` — Ponto de entrada da linha de comando.

- `_print(payload) → None` — Imprime um payload em JSON.
- `_run_forever(settings, interval) → None` — Roda o supervisor e o worker autônomo até receber um sinal de parada.
- `_request_stop(*_args) → None` — Envia o pedido de parada do supervisor e devolve a resposta do comando.
### `src/agent/automation/contracts.py`

**Propósito:** contracts — módulo do projeto.

- `TriggerSpec` — Gatilho: quando a automação acorda.
- `CallidusAction` — Ação Callidus: cria ou retoma um trabalho pelos serviços existentes.
- `ScriptAction` — Ação de script: execução determinística, sem depender de inferência.
- `parse_action(data) → CallidusAction | ScriptAction` — Valida um dicionário de ação (JSON persistido ou payload da API).
- `dump_action(action) → dict` — Serializa a ação para JSON (persistência).
- `StartStrategy` — Como iniciar a dependência quando ela não está pronta.
- `DependencySpec` — Dependência que precisa estar pronta antes da ação rodar.
- `PermissionSpec` — Permissões decididas antes do disparo — o modelo não as amplia durante a execução.
- `RecoveryPolicy` — Política de recuperação da ação.
- `AutomationDefinition` — Definição completa de uma automação — o que a API e a interface enviam.
- `model_post_init(self, _context) → None` — Confere que os campos exigidos pelo tipo de gatilho estão presentes.
- `label(self) → str` — Rótulo legível da dependência, para mensagens e evidências.

- `_fuso_valido(cls, value) → str` — Valida o fuso informado no gatilho.
- `_comando_lista(cls, value) → list[str]` — Normaliza o comando da ação de script em uma lista de textos não vazios.
- `_fuso_valido(cls, value) → str` — Valida o fuso informado na definição.

- `TriggerSpec._fuso_valido(cls, value) → str` — Valida o fuso informado no gatilho.
- `TriggerSpec.model_post_init(self, _context) → None` — Confere que os campos exigidos pelo tipo de gatilho estão presentes.
- `ScriptAction._comando_lista(cls, value) → list[str]` — Normaliza o comando da ação de script em uma lista de textos não vazios.
- `DependencySpec.label(self) → str` — Rótulo legível da dependência, para mensagens e evidências.
- `AutomationDefinition._fuso_valido(cls, value) → str` — Valida o fuso informado na definição.
### `src/agent/automation/dependencies.py`

**Propósito:** dependencies — módulo do projeto.

- `DependencyReport` — Estado de uma dependência.
- `DependencyCheck` — Resultado agregado da verificação.
- `DependencyResolver` — Resolve e verifica as dependências declaradas por uma automação.
- `sh_quote(value) → str` — Cita um valor para o shell POSIX.
- `as_dict(self) → dict[str, Any]` — Serializa a dependência para o registro da automação.
- `ok(self) → bool` — Pronta quando toda dependência **crítica** está pronta.
- `blocking(self) → list[DependencyReport]` — Indica se a dependência impede a execução quando não está satisfeita.
- `as_dict(self) → dict[str, Any]` — Verificação agregada como dicionário serializável.
- `check_all(self, specs) → DependencyCheck` — Verifica todas as dependências e aciona a inicialização autorizada.

- `_remote_config(remote_cfg)` — Configuração do destino remoto, convertida no contrato do transporte SSH.
- `_check_one(self, spec) → DependencyReport` — Verifica uma dependência conforme o seu tipo.
- `_check_project_dir(self, spec) → DependencyReport` — Verifica a pasta do projeto da automação.
- `_check_workdir(self, spec) → DependencyReport` — Verifica a pasta de trabalho declarada pela automação.
- `_check_os(self, spec) → DependencyReport` — Verifica se o sistema operacional exigido está disponível.
- `_target_os_family(self) → str` — Família de sistema do destino da automação.
- `_check_interpreter(self, spec) → DependencyReport` — Verifica o interpretador configurado para a automação.
- `_check_script(self, spec) → DependencyReport` — Verifica o script declarado pela automação.
- `_check_remote(self, spec) → DependencyReport` — Verifica o computador remoto declarado pela automação.
- `_check_provider(self, spec) → DependencyReport` — Verifica o provedor de modelo exigido pela automação.
- `_check_tool(self, spec) → DependencyReport` — Verifica a ferramenta exigida pela automação.
- `_check_mcp(self, spec) → DependencyReport` — Verifica o servidor MCP exigido pela automação.
- `_check_credential(self, spec) → DependencyReport` — Confere a existência da credencial **sem** revelar o valor.
- `_can_start(self, spec) → bool` — Indica se a dependência pode ser iniciada automaticamente.
- `_start(self, spec) → tuple[bool, str]` — Executa a estratégia de inicialização da dependência.
- `_start_command(self, strategy) → tuple[bool, str]` — Executa o comando de inicialização, local ou remoto.
- `_start_service(self, strategy) → tuple[bool, str]` — Reinicia o serviço nativo declarado na estratégia.
- `_remote_service(self, name, strategy) → tuple[bool, str]` — Reinicia o serviço no computador remoto.
- `_start_mcp(self, spec, strategy) → tuple[bool, str]` — Reinicia um processo MCP gerenciado (o `McpManager` recarrega a configuração).
- `_remote_which(self, name) → tuple[bool, str]` — Procura um executável no computador remoto.

- `DependencyReport.as_dict(self) → dict[str, Any]` — Serializa a dependência para o registro da automação.
- `DependencyCheck.ok(self) → bool` — Pronta quando toda dependência **crítica** está pronta.
- `DependencyCheck.blocking(self) → list[DependencyReport]` — Indica se a dependência impede a execução quando não está satisfeita.
- `DependencyCheck.as_dict(self) → dict[str, Any]` — Verificação agregada como dicionário serializável.
- `DependencyResolver.check_all(self, specs) → DependencyCheck` — Verifica todas as dependências e aciona a inicialização autorizada.
- `DependencyResolver._check_one(self, spec) → DependencyReport` — Verifica uma dependência conforme o seu tipo.
- `DependencyResolver._check_project_dir(self, spec) → DependencyReport` — Verifica a pasta do projeto da automação.
- `DependencyResolver._check_workdir(self, spec) → DependencyReport` — Verifica a pasta de trabalho declarada pela automação.
- `DependencyResolver._check_os(self, spec) → DependencyReport` — Verifica se o sistema operacional exigido está disponível.
- `DependencyResolver._target_os_family(self) → str` — Família de sistema do destino da automação.
- `DependencyResolver._check_interpreter(self, spec) → DependencyReport` — Verifica o interpretador configurado para a automação.
- `DependencyResolver._check_script(self, spec) → DependencyReport` — Verifica o script declarado pela automação.
- `DependencyResolver._check_remote(self, spec) → DependencyReport` — Verifica o computador remoto declarado pela automação.
- `DependencyResolver._check_provider(self, spec) → DependencyReport` — Verifica o provedor de modelo exigido pela automação.
- `DependencyResolver._check_tool(self, spec) → DependencyReport` — Verifica a ferramenta exigida pela automação.
- `DependencyResolver._check_mcp(self, spec) → DependencyReport` — Verifica o servidor MCP exigido pela automação.
- `DependencyResolver._check_credential(self, spec) → DependencyReport` — Confere a existência da credencial **sem** revelar o valor.
- `DependencyResolver._can_start(self, spec) → bool` — Indica se a dependência pode ser iniciada automaticamente.
- `DependencyResolver._start(self, spec) → tuple[bool, str]` — Executa a estratégia de inicialização da dependência.
- `DependencyResolver._start_command(self, strategy) → tuple[bool, str]` — Executa o comando de inicialização, local ou remoto.
- `DependencyResolver._start_service(self, strategy) → tuple[bool, str]` — Reinicia o serviço nativo declarado na estratégia.
- `DependencyResolver._remote_service(self, name, strategy) → tuple[bool, str]` — Reinicia o serviço no computador remoto.
- `DependencyResolver._start_mcp(self, spec, strategy) → tuple[bool, str]` — Reinicia um processo MCP gerenciado (o `McpManager` recarrega a configuração).
- `DependencyResolver._remote_which(self, name) → tuple[bool, str]` — Procura um executável no computador remoto.

- `DependencyResolver.__init__(self, *, settings, project_root, remote, target_kind) → None` — Cria o verificador de dependências.
### `src/agent/automation/dispatcher.py`

**Propósito:** dispatcher — módulo do projeto.

- `DispatchResult` — O que o despachante fez.
- `temporal_key(automation_id, kind, moment) → str` — Chave de idempotência de um disparo temporal.
- `event_key(automation_id, source, event_id) → str` — Chave de idempotência de um disparo por evento.
- `manual_key(automation_id, tag) → str` — Chave de idempotência de um disparo manual, sempre única.
- `Dispatcher` — Registra disparos elegíveis.
- `as_dict(self) → dict` — Desfecho do despacho como dicionário serializável.
- `dispatch_due(self, automation, *, now) → DispatchResult` — Registra os disparos vencidos de uma automação temporal.
- `dispatch_event(self, automation, candidate) → AutomationFiringModel | None` — Registra o disparo de um evento interno (idempotente pelo identificador do evento).
- `dispatch_manual(self, automation, *, tag, state, result, scheduled_for) → AutomationFiringModel | None` — Disparo manual ("executar agora", "testar"). Sempre único.

- `_create(self, automation, *, key, scheduled_for, state, result) → AutomationFiringModel | None` — Cria a linha de disparo, respeitando a chave de idempotência.
- `_advance(self, automation, last_occurrence, now) → None` — Avança o marcador de última execução e recalcula o próximo disparo.

- `DispatchResult.as_dict(self) → dict` — Desfecho do despacho como dicionário serializável.
- `Dispatcher.dispatch_due(self, automation, *, now) → DispatchResult` — Registra os disparos vencidos de uma automação temporal.
- `Dispatcher.dispatch_event(self, automation, candidate) → AutomationFiringModel | None` — Registra o disparo de um evento interno (idempotente pelo identificador do evento).
- `Dispatcher.dispatch_manual(self, automation, *, tag, state, result, scheduled_for) → AutomationFiringModel | None` — Disparo manual ("executar agora", "testar"). Sempre único.
- `Dispatcher._create(self, automation, *, key, scheduled_for, state, result) → AutomationFiringModel | None` — Cria a linha de disparo, respeitando a chave de idempotência.
- `Dispatcher._advance(self, automation, last_occurrence, now) → None` — Avança o marcador de última execução e recalcula o próximo disparo.

- `Dispatcher.__init__(self, session) → None` — Cria o despachante ligado a uma sessão.
### `src/agent/automation/enums.py`

**Propósito:** enums — módulo do projeto.

- `AutomationState` — Estado da definição da automação (o que o usuário controla).
- `TriggerKind` — Modalidades iniciais de gatilho. Novas modalidades entram por registro.
- `ActionKind` — Tipos de ação. A arquitetura permite novos tipos por registro.
- `TargetKind` — Onde a ação acontece: nesta máquina ou no computador remoto do projeto.
- `ObjectiveMode` — Como a automação escolhe o objetivo de uma conversa/tarefa.
- `MissedPolicy` — O que fazer com disparos perdidos durante uma interrupção.
- `DependencyKind` — Tipos de dependência verificável antes da execução.
- `StartMechanism` — Como uma dependência pode ser iniciada automaticamente.
- `FiringState` — Estados do disparo (a máquina de estados do trabalho executado).

### `src/agent/automation/executor.py`

**Propósito:** executor — módulo do projeto.

- `ExecutionOutcome` — Desfecho da execução de um disparo.
- `AutomationExecutor` — Executa disparos de automação.
- `execute(self, firing) → ExecutionOutcome` — Executa um disparo: dependências, ação, evidência e estado.
- `reconcile(self) → list[ExecutionOutcome]` — Fecha os disparos que ficaram rodando, olhando o estado real do run.

- `_seconds(value)` — Converte segundos em um intervalo de tempo.
- `_target_info(self, automation) → dict[str, Any]` — Resolve o destino da automação: local ou remoto, com suas permissões.
- `_next_attempt(self, policy, attempt) → datetime` — Instante da próxima tentativa, com backoff exponencial limitado.
- `_log(self, automation, firing, event_type, payload) → None` — Registra um fato da automação no log de eventos.

- `AutomationExecutor._target_info(self, automation) → dict[str, Any]` — Resolve o destino da automação: local ou remoto, com suas permissões.
- `AutomationExecutor.execute(self, firing) → ExecutionOutcome` — Executa um disparo: dependências, ação, evidência e estado.
- `AutomationExecutor.reconcile(self) → list[ExecutionOutcome]` — Fecha os disparos que ficaram rodando, olhando o estado real do run.
- `AutomationExecutor._next_attempt(self, policy, attempt) → datetime` — Instante da próxima tentativa, com backoff exponencial limitado.
- `AutomationExecutor._log(self, automation, firing, event_type, payload) → None` — Registra um fato da automação no log de eventos.

- `AutomationExecutor.__init__(self, session, settings) → None` — Cria o executor ligado a uma sessão.
### `src/agent/automation/security.py`

**Propósito:** security — módulo do projeto.

- `PermissionDenied` — A execução não está autorizada pela definição aprovada.
- `command_allowed(command, permissions) → bool` — O executável (primeiro item) está na allowlist?.
- `assert_script_allowed(command, permissions) → None` — Valida a autorização de um script antes de executá-lo.
- `resolve_workdir(cwd, *, project_root, permissions) → Path` — Resolve o diretório de trabalho dentro do escopo autorizado.
- `assert_path_allowed(path, permissions, *, project_root) → Path` — Valida um caminho explícito (script, recibo) contra os escopos autorizados.
- `build_env(extra, *, allow_inherit) → dict[str, str]` — Ambiente controlado: herda o ambiente do processo (sem segredos novos) e aplica o extra.
- `redact_evidence(evidence) → dict[str, Any]` — Sanitiza a evidência antes de persistir (segredos não entram no banco nem nos logs).
- `which_or_none(executable) → str | None` — Localiza um executável no `PATH`.

- `PermissionDenied.__init__(self, message, *, reason) → None` — Registra a violação com o caminho e o motivo.
### `src/agent/automation/service/__init__.py`

**Propósito:** __init__ — módulo do projeto.

- `current_adapter() → ServiceAdapter` — Adaptador da plataforma atual (o primeiro compatível).
- `adapters_status() → list[dict]` — Situação de todos os adaptadores (útil para diagnóstico multiplataforma).

### `src/agent/automation/service/base.py`

**Propósito:** base — módulo do projeto.

- `ServiceOptions` — Como o serviço nativo deve chamar o runtime.
- `ServiceStatus` — Situação do serviço nativo.
- `ServiceAdapter` — Interface dos adaptadores de serviço.
- `default_options() → ServiceOptions` — Opções padrão: executa o supervisor a partir do pacote instalado.
- `as_dict(self) → dict[str, Any]` — Situação do serviço como dicionário serializável.
- `available(self) → bool` — Este adaptador funciona nesta máquina?.
- `install(self, options) → dict[str, Any]` — Instala o serviço nativo.
- `uninstall(self) → dict[str, Any]` — Remove o serviço nativo.
- `start(self) → dict[str, Any]` — Inicia o serviço.
- `stop(self) → dict[str, Any]` — Para o serviço.
- `status(self) → ServiceStatus` — Situação do serviço.

- `_run(self, args, *, timeout) → tuple[int, str, str]` — Executa um comando do sistema operacional.
- `_which(self, executable) → str | None` — Localiza um executável no `PATH`.
- `_home(self) → Path` — Pasta pessoal do usuário.

- `ServiceStatus.as_dict(self) → dict[str, Any]` — Situação do serviço como dicionário serializável.
- `ServiceAdapter.available(self) → bool` — Este adaptador funciona nesta máquina?.
- `ServiceAdapter.install(self, options) → dict[str, Any]` — Instala o serviço nativo.
- `ServiceAdapter.uninstall(self) → dict[str, Any]` — Remove o serviço nativo.
- `ServiceAdapter.start(self) → dict[str, Any]` — Inicia o serviço.
- `ServiceAdapter.stop(self) → dict[str, Any]` — Para o serviço.
- `ServiceAdapter.status(self) → ServiceStatus` — Situação do serviço.
- `ServiceAdapter._run(self, args, *, timeout) → tuple[int, str, str]` — Executa um comando do sistema operacional.
- `ServiceAdapter._which(self, executable) → str | None` — Localiza um executável no `PATH`.
- `ServiceAdapter._home(self) → Path` — Pasta pessoal do usuário.
### `src/agent/automation/service/launchd.py`

**Propósito:** launchd — módulo do projeto.

- `LaunchdAdapter` — Adaptador do `launchd` (macOS).
- `available(self) → bool` — Indica se o `launchd` pode ser usado nesta máquina.
- `install(self, options) → dict[str, Any]` — Grava o `plist` e carrega o agente no `launchd`.
- `uninstall(self) → dict[str, Any]` — Descarrega o agente e apaga o `plist`.
- `start(self) → dict[str, Any]` — Inicia o agente do `launchd`.
- `stop(self) → dict[str, Any]` — Para o agente do `launchd`.
- `status(self) → ServiceStatus` — Situação do agente do `launchd`.

- `_plist_path(self, label) → Path` — Caminho do arquivo `plist` do agente.

- `LaunchdAdapter._plist_path(self, label) → Path` — Caminho do arquivo `plist` do agente.
- `LaunchdAdapter.available(self) → bool` — Indica se o `launchd` pode ser usado nesta máquina.
- `LaunchdAdapter.install(self, options) → dict[str, Any]` — Grava o `plist` e carrega o agente no `launchd`.
- `LaunchdAdapter.uninstall(self) → dict[str, Any]` — Descarrega o agente e apaga o `plist`.
- `LaunchdAdapter.start(self) → dict[str, Any]` — Inicia o agente do `launchd`.
- `LaunchdAdapter.stop(self) → dict[str, Any]` — Para o agente do `launchd`.
- `LaunchdAdapter.status(self) → ServiceStatus` — Situação do agente do `launchd`.
### `src/agent/automation/service/systemd.py`

**Propósito:** systemd — módulo do projeto.

- `SystemdAdapter` — Adaptador do `systemd` (Linux).
- `available(self) → bool` — Indica se o `systemd` pode ser usado nesta máquina.
- `install(self, options) → dict[str, Any]` — Grava a unidade, recarrega o `systemd` e habilita o serviço.
- `uninstall(self) → dict[str, Any]` — Para, desabilita e apaga a unidade nos dois escopos.
- `start(self) → dict[str, Any]` — Inicia o serviço de usuário.
- `stop(self) → dict[str, Any]` — Para o serviço de usuário.
- `status(self) → ServiceStatus` — Situação do serviço, consultando o escopo de usuário e o de sistema.

- `_user_unit_path(self) → Path` — Caminho da unidade de usuário.
- `_system_unit_path(self) → Path` — Caminho da unidade de sistema.
- `_unit_path(self, scope) → Path` — Caminho da unidade conforme o escopo.
- `_ctl(self, args, scope) → tuple[int, str, str]` — Chama o `systemctl` no escopo pedido.
- `_unit_content(self, options) → str` — Conteúdo do arquivo de unidade.

- `SystemdAdapter._user_unit_path(self) → Path` — Caminho da unidade de usuário.
- `SystemdAdapter._system_unit_path(self) → Path` — Caminho da unidade de sistema.
- `SystemdAdapter._unit_path(self, scope) → Path` — Caminho da unidade conforme o escopo.
- `SystemdAdapter._ctl(self, args, scope) → tuple[int, str, str]` — Chama o `systemctl` no escopo pedido.
- `SystemdAdapter.available(self) → bool` — Indica se o `systemd` pode ser usado nesta máquina.
- `SystemdAdapter._unit_content(self, options) → str` — Conteúdo do arquivo de unidade.
- `SystemdAdapter.install(self, options) → dict[str, Any]` — Grava a unidade, recarrega o `systemd` e habilita o serviço.
- `SystemdAdapter.uninstall(self) → dict[str, Any]` — Para, desabilita e apaga a unidade nos dois escopos.
- `SystemdAdapter.start(self) → dict[str, Any]` — Inicia o serviço de usuário.
- `SystemdAdapter.stop(self) → dict[str, Any]` — Para o serviço de usuário.
- `SystemdAdapter.status(self) → ServiceStatus` — Situação do serviço, consultando o escopo de usuário e o de sistema.
### `src/agent/automation/service/windows.py`

**Propósito:** windows — módulo do projeto.

- `WindowsTaskAdapter` — Adaptador do Agendador de Tarefas (Windows).
- `available(self) → bool` — Indica se o Agendador de Tarefas pode ser usado nesta máquina.
- `install(self, options) → dict[str, Any]` — Cria a tarefa agendada, no escopo de usuário ou de sistema.
- `uninstall(self) → dict[str, Any]` — Apaga a tarefa agendada.
- `start(self) → dict[str, Any]` — Executa a tarefa agendada agora.
- `stop(self) → dict[str, Any]` — Interrompe a execução da tarefa agendada.
- `status(self) → ServiceStatus` — Situação da tarefa agendada.

- `_task_name(self) → str` — Nome da tarefa agendada.
- `_is_admin(self) → bool` — Indica se o processo roda com privilégio administrativo.

- `WindowsTaskAdapter.available(self) → bool` — Indica se o Agendador de Tarefas pode ser usado nesta máquina.
- `WindowsTaskAdapter._task_name(self) → str` — Nome da tarefa agendada.
- `WindowsTaskAdapter.install(self, options) → dict[str, Any]` — Cria a tarefa agendada, no escopo de usuário ou de sistema.
- `WindowsTaskAdapter.uninstall(self) → dict[str, Any]` — Apaga a tarefa agendada.
- `WindowsTaskAdapter.start(self) → dict[str, Any]` — Executa a tarefa agendada agora.
- `WindowsTaskAdapter.stop(self) → dict[str, Any]` — Interrompe a execução da tarefa agendada.
- `WindowsTaskAdapter.status(self) → ServiceStatus` — Situação da tarefa agendada.
- `WindowsTaskAdapter._is_admin(self) → bool` — Indica se o processo roda com privilégio administrativo.
### `src/agent/automation/store.py`

**Propósito:** store — módulo do projeto.

- `AutomationNotFound` — Automação inexistente ou com identificador inválido.
- `AutomationService` — Serviço das automações de um projeto.
- `get(self, automation_id) → AutomationModel` — Automação por identificador.
- `list(self, project_id, *, state) → list[AutomationModel]` — Automações do catálogo, filtradas por projeto e por estado.
- `enabled(self) → list[AutomationModel]` — Automações habilitadas, que o supervisor deve vigiar.
- `create(self, definition) → AutomationModel` — Grava a definição aprovada de uma automação.
- `update(self, automation_id, changes) → AutomationModel` — Aplica alterações na definição de uma automação.
- `set_state(self, automation_id, state) → AutomationModel` — Muda o estado da automação (habilitada, suspensa ou desabilitada).
- `delete(self, automation_id) → bool` — Remove uma automação.
- `to_definition(self, row) → AutomationDefinition` — Documento validado da automação gravada.
- `trigger_of(self, row)` — Gatilho da automação, já instanciado.
- `next_occurrence(self, row, *, after) → datetime | None` — Próximo instante elegível da automação.

- `_uuid_or_none(value) → uuid.UUID | None` — Converte um valor em UUID, tolerando ausência e texto inválido.
- `_recompute_next_run(self, row) → None` — Recalcula o próximo disparo a partir do gatilho da definição.
- `_objective_snapshot(self, definition, *, action) → dict | None` — Congela o objetivo no momento da aprovação (modo `frozen`).
- `_log(self, row, event_type, payload) → None` — Registra um fato da automação no log de eventos.

- `AutomationService.get(self, automation_id) → AutomationModel` — Automação por identificador.
- `AutomationService.list(self, project_id, *, state) → list[AutomationModel]` — Automações do catálogo, filtradas por projeto e por estado.
- `AutomationService.enabled(self) → list[AutomationModel]` — Automações habilitadas, que o supervisor deve vigiar.
- `AutomationService.create(self, definition) → AutomationModel` — Grava a definição aprovada de uma automação.
- `AutomationService.update(self, automation_id, changes) → AutomationModel` — Aplica alterações na definição de uma automação.
- `AutomationService.set_state(self, automation_id, state) → AutomationModel` — Muda o estado da automação (habilitada, suspensa ou desabilitada).
- `AutomationService.delete(self, automation_id) → bool` — Remove uma automação.
- `AutomationService.to_definition(self, row) → AutomationDefinition` — Documento validado da automação gravada.
- `AutomationService.trigger_of(self, row)` — Gatilho da automação, já instanciado.
- `AutomationService.next_occurrence(self, row, *, after) → datetime | None` — Próximo instante elegível da automação.
- `AutomationService._recompute_next_run(self, row) → None` — Recalcula o próximo disparo a partir do gatilho da definição.
- `AutomationService._objective_snapshot(self, definition, *, action) → dict | None` — Congela o objetivo no momento da aprovação (modo `frozen`).
- `AutomationService._log(self, row, event_type, payload) → None` — Registra um fato da automação no log de eventos.

- `AutomationService.__init__(self, session) → None` — Cria o serviço ligado a uma sessão.
### `src/agent/automation/supervisor.py`

**Propósito:** supervisor — módulo do projeto.

- `SupervisorStats` — Contadores do runtime de automações.
- `AutomationSupervisor` — Núcleo do runtime de automações — compartilhado pela API e pelo supervisor nativo.
- `build_supervisor(settings) → AutomationSupervisor` — Supervisor com o banco inicializado (cria as tabelas que faltarem).
- `find_automation(session, automation_id) → AutomationModel | None` — Procura uma automação pelo identificador.
- `as_dict(self) → dict[str, Any]` — Contadores como dicionário serializável.
- `stop(self) → None` — Pede o encerramento do laço do supervisor.
- `run_forever(self, interval_sec) → None` — Laço principal do supervisor.
- `tick(self) → dict[str, Any]` — Um ciclo completo: recuperação → disparo → execução.
- `status(self) → dict[str, Any]` — Situação do runtime: automações, disparos e contadores.
- `diagnose(self) → dict[str, Any]` — Diagnóstico detalhado: automações vencidas, dependências e disparos pendentes.

- `_heartbeat(self, session) → None` — Grava o batimento do runtime — é o que `status` mostra de outro processo.
- `_tick_with(self, session) → dict[str, Any]` — Executa as três etapas do tique em uma sessão.
- `_recover(self, session, service, executor) → int` — Recupera disparos interrompidos por encerramento do processo.
- `_dispatch(self, session, service, dispatcher, now) → dict[str, Any]` — Registra os disparos vencidos e os eventos elegíveis.
- `_execute(self, session, executor, now) → list[dict]` — Executa os disparos prontos e reconcilia os que ficaram rodando.
- `_read_heartbeat(self, session) → dict[str, Any] | None` — Batimento gravado pelo runtime em execução (visível de outro processo).

- `SupervisorStats.as_dict(self) → dict[str, Any]` — Contadores como dicionário serializável.
- `AutomationSupervisor.stop(self) → None` — Pede o encerramento do laço do supervisor.
- `AutomationSupervisor.run_forever(self, interval_sec) → None` — Laço principal do supervisor.
- `AutomationSupervisor.tick(self) → dict[str, Any]` — Um ciclo completo: recuperação → disparo → execução.
- `AutomationSupervisor._heartbeat(self, session) → None` — Grava o batimento do runtime — é o que `status` mostra de outro processo.
- `AutomationSupervisor._tick_with(self, session) → dict[str, Any]` — Executa as três etapas do tique em uma sessão.
- `AutomationSupervisor._recover(self, session, service, executor) → int` — Recupera disparos interrompidos por encerramento do processo.
- `AutomationSupervisor._dispatch(self, session, service, dispatcher, now) → dict[str, Any]` — Registra os disparos vencidos e os eventos elegíveis.
- `AutomationSupervisor._execute(self, session, executor, now) → list[dict]` — Executa os disparos prontos e reconcilia os que ficaram rodando.
- `AutomationSupervisor.status(self) → dict[str, Any]` — Situação do runtime: automações, disparos e contadores.
- `AutomationSupervisor._read_heartbeat(self, session) → dict[str, Any] | None` — Batimento gravado pelo runtime em execução (visível de outro processo).
- `AutomationSupervisor.diagnose(self) → dict[str, Any]` — Diagnóstico detalhado: automações vencidas, dependências e disparos pendentes.

- `AutomationSupervisor.__init__(self, settings, *, session_factory) → None` — Cria o supervisor.
### `src/agent/automation/timezones.py`

**Propósito:** timezones — módulo do projeto.

- `resolve_timezone(name) → str` — Normaliza e valida um nome de fuso. `None`/vazio vira `UTC`.
- `to_utc(value) → datetime` — Normaliza um datetime para UTC. Sem fuso, assume UTC.
- `localize(naive_local, tz_name) → datetime` — Converte um horário local (sem fuso) no instante UTC correspondente.
- `next_cron_occurrence(expression, tz_name, after, *, limit) → list[datetime]` — Próximas ocorrências de uma expressão cron, em UTC.
- `occurrences_between(expression, tz_name, start, end, *, limit) → list[datetime]` — Ocorrências de cron dentro de uma janela (UTC, inclusiva no início).
- `seconds_until(now, target) → float` — Segundos entre dois instantes (pode ser negativo).
- `floor_minute(moment) → datetime` — Arredonda para o minuto — usado para detectar o mesmo minuto de disparo.
- `add_interval(moment, seconds) → datetime` — Soma um intervalo a um instante, em UTC.

### `src/agent/automation/triggers/__init__.py`

**Propósito:** __init__ — módulo do projeto.

### `src/agent/automation/triggers/base.py`

**Propósito:** base — módulo do projeto.

- `Trigger` — O mínimo que o runtime precisa de um gatilho.
- `register_trigger(kind, factory) → None` — Registra (ou substitui) um tipo de gatilho.
- `trigger_factories() → dict[str, TriggerFactory]` — Fábricas de gatilho registradas.
- `build_trigger(spec) → Trigger` — Instancia o gatilho de uma especificação.
- `next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois de `after` (UTC).
- `occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela (UTC) — usado para recuperar disparos perdidos.

- `Trigger.next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois de `after` (UTC).
- `Trigger.occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela (UTC) — usado para recuperar disparos perdidos.
### `src/agent/automation/triggers/internal.py`

**Propósito:** internal — módulo do projeto.

- `EventCandidate` — Um evento elegível, pronto para virar disparo.
- `EventTrigger` — Gatilho de evento interno.
- `with_project(self, project_id) → 'EventTrigger'` — Restringe o gatilho aos eventos de um projeto.
- `event_types(self) → list[str]` — Tipos de evento escutados pelo gatilho.
- `next_occurrence(self, after) → datetime | None` — Eventos não têm horário próprio: o próximo disparo depende do evento.
- `occurrences(self, start, end, *, limit) → list[datetime]` — Eventos não têm horário próprio: nada a listar na janela.
- `candidate_events(self, session, *, since, limit) → list[EventCandidate]` — Eventos elegíveis, dos mais recentes para os mais antigos.

- `_matches_filter(payload, criteria) → bool` — Confere se o payload casa com os critérios de filtro do gatilho.

- `EventTrigger.with_project(self, project_id) → 'EventTrigger'` — Restringe o gatilho aos eventos de um projeto.
- `EventTrigger.event_types(self) → list[str]` — Tipos de evento escutados pelo gatilho.
- `EventTrigger.next_occurrence(self, after) → datetime | None` — Eventos não têm horário próprio: o próximo disparo depende do evento.
- `EventTrigger.occurrences(self, start, end, *, limit) → list[datetime]` — Eventos não têm horário próprio: nada a listar na janela.
- `EventTrigger.candidate_events(self, session, *, since, limit) → list[EventCandidate]` — Eventos elegíveis, dos mais recentes para os mais antigos.

- `EventTrigger.__init__(self, spec) → None` — Cria o gatilho a partir da sua especificação.
### `src/agent/automation/triggers/temporal.py`

**Propósito:** temporal — módulo do projeto.

- `OnceTrigger` — Execução única em um instante determinado.
- `CronTrigger` — Recorrência por expressão cron (5 ou 6 campos).
- `IntervalTrigger` — Recorrência por intervalo fixo, contado a partir do horário de referência.
- `DailyAtTrigger` — Atalho: todo dia, no horário local informado (ex.: `09:30` no fuso da automação).
- `next_occurrence(self, after) → datetime | None` — Instante único, quando ainda está no futuro.
- `occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.
- `next_occurrence(self, after) → datetime | None` — Devolve a próxima ocorrência do gatilho a partir de um instante.
- `occurrences(self, start, end, *, limit) → list[datetime]` — Devolve as próximas ocorrências do gatilho dentro de uma janela.
- `next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois do instante informado.
- `occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.
- `next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois do instante informado.
- `occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.

- `OnceTrigger.next_occurrence(self, after) → datetime | None` — Instante único, quando ainda está no futuro.
- `OnceTrigger.occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.
- `CronTrigger.next_occurrence(self, after) → datetime | None` — Devolve a próxima ocorrência do gatilho a partir de um instante.
- `CronTrigger.occurrences(self, start, end, *, limit) → list[datetime]` — Devolve as próximas ocorrências do gatilho dentro de uma janela.
- `IntervalTrigger.next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois do instante informado.
- `IntervalTrigger.occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.
- `DailyAtTrigger.next_occurrence(self, after) → datetime | None` — Próximo instante elegível depois do instante informado.
- `DailyAtTrigger.occurrences(self, start, end, *, limit) → list[datetime]` — Instantes elegíveis na janela.

- `OnceTrigger.__init__(self, spec) → None` — Cria o gatilho de execução única.
- `CronTrigger.__init__(self, spec) → None` — Cria o gatilho de recorrência por cron.
- `IntervalTrigger.__init__(self, spec) → None` — Cria o gatilho de intervalo fixo.
- `DailyAtTrigger.__init__(self, spec) → None` — Cria o gatilho diário a partir do horário `HH:MM` informado.
### `src/agent/brand.py`

**Propósito:** brand — módulo do projeto.

- `is_attachments_dir(rel) → bool` — True quando o caminho relativo aponta para a pasta de anexos (nova ou legada).

### `src/agent/domain/agent_enums.py`

**Propósito:** agent_enums — módulo do projeto.

- `AgentStatus` — Estado do agente lógico. Não é o estado da tarefa: o agente sobrevive à tarefa.
- `ExecutionStatus` — Estado da execução — a parte que ocupa memória de inferência.
- `QueryStatus` — Estado da consulta entre agentes.

### `src/agent/domain/agent_lifecycle.py`

**Propósito:** agent_lifecycle — módulo do projeto.

- `InvalidAgentTransition` — Transição de estado de agente ou execução não permitida.
- `can_transition_agent(current, target) → bool` — Indica se a mudança de estado do agente lógico é permitida.
- `can_transition_execution(current, target) → bool` — Indica se a mudança de estado da execução é permitida.
- `validate_agent_transition(current, target) → None` — Valida a mudança de estado do agente, levantando erro quando inválida.
- `validate_execution_transition(current, target) → None` — Valida a mudança de estado da execução, levantando erro quando inválida.
- `transition_agent(current, target) → AgentStatus` — Devolve o novo estado do agente após validar a transição.
- `transition_execution(current, target) → ExecutionStatus` — Devolve o novo estado da execução após validar a transição.

- `InvalidAgentTransition.__init__(self, current, target) → None` — Monta o registro de ciclo de vida do agente.
### `src/agent/orchestrator/plan_contract.py`

**Propósito:** plan_contract — módulo do projeto.

- `normalize_kind(raw) → tuple[TaskKind, str | None]` — `kind` do modelo → `TaskKind`. Rótulo desconhecido vira `operation` com aviso, nunca erro.
- `is_final_answer_label(raw) → bool` — Diz se um rótulo de `kind` indica a etapa de resposta final.
- `normalize_depends(raw) → tuple[list[int], list[str]]` — `depends_on_indices` → índices inteiros válidos. Índice inválido é descartado com aviso:.
- `normalize_covers(raw) → list[dict[str, Any]] | None` — `metadata.covers` → lista uniforme. `None` quando não declarado (a cobertura é herdada).
- `normalize_plan_payload(data) → tuple[dict[str, Any], list[str]]` — Payload cru do modelo → payload no formato de `DecompositionResult`, com avisos.

### `src/agent/orchestrator/tool_loop.py`

**Propósito:** tool_loop — módulo do projeto.

- `ToolLoopOutcome` — Resultado do ciclo: o que o modelo respondeu e o que ele pediu no caminho.
- `json_schema_for(spec) → dict[str, Any]` — Traduz o `input_schema` da ferramenta (forma simplificada do Callidus) para JSON Schema.
- `tool_schemas(registry, tool_ids) → list[dict[str, Any]]` — Esquemas no formato de função (OpenAI/Ollama) para as ferramentas pedidas.
- `tool_result_text(result, limit) → str` — Resultado da ferramenta como texto para o modelo (curto e sem metadados internos).
- `run_tool_loop(*, provider, messages, profile, registry, ctx, approved, tool_ids, max_iterations, max_tool_calls, final_tools, final_tools_after, final_instruction, final_instruction_after, purpose, stream, chat, on_tool_call, payload_ok, deliverable_hint, tool_guard) → ToolLoopOutcome` — Chama o modelo em ciclo: ele pede ferramentas, o agente as executa, o modelo prossegue.
- `asked_tools(self) → list[str]` — Lista as ferramentas que o modelo pediu no ciclo.
- `applied(self) → bool` — Diz se o modelo deixou alguma alteração aplicada no disco.

- `_execute(call_item) → tuple[dict[str, Any], dict[str, Any]]` — Executa uma chamada de ferramenta pedida pelo modelo.
- `_budget_note() → str` — Monta a nota de orçamento de chamadas de ferramenta que entra na conversa.

- `ToolLoopOutcome.asked_tools(self) → list[str]` — Lista as ferramentas que o modelo pediu no ciclo.
- `ToolLoopOutcome.applied(self) → bool` — Diz se o modelo deixou alguma alteração aplicada no disco.
### `src/agent/providers/anthropic.py`

**Propósito:** anthropic — módulo do projeto.

- `anthropic_messages(messages) → tuple[str, list[dict[str, Any]]]` — Separa o prompt de sistema (campo `system` da API) das mensagens de conversa.
- `anthropic_tools(tools) → list[dict[str, Any]] | None` — Converte o formato de ferramenta do Callidus (OpenAI) para o da Anthropic.
- `AnthropicProvider` — Anthropic Messages API (`/v1/messages`). A API não é compatível com OpenAI: usa.
- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `list_models(self, *, force) → list[str]` — Lista os modelos disponíveis na API, com cache curto.

- `_media_type(encoded) → str` — Deduz o tipo de mídia de uma imagem codificada em base64.
- `_image_block(encoded) → dict[str, Any]` — Monta o bloco de imagem aceito pela Messages API.
- `_client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `_body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da Messages API.
- `_parse(data) → tuple[str, list[ToolCall] | None, str | None]` — Extrai texto, chamadas de ferramenta e motivo de término da resposta da API.
- `_chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela Messages API.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela Messages API.

- `AnthropicProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `AnthropicProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `AnthropicProvider.list_models(self, *, force) → list[str]` — Lista os modelos disponíveis na API, com cache curto.
- `AnthropicProvider._body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da Messages API.
- `AnthropicProvider._parse(data) → tuple[str, list[ToolCall] | None, str | None]` — Extrai texto, chamadas de ferramenta e motivo de término da resposta da API.
- `AnthropicProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela Messages API.
- `AnthropicProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela Messages API.

- `AnthropicProvider.__init__(self, base_url, *, model, api_key, headers, timeout, max_retries, allow_private_hosts, verify_tls, anthropic_version, models_cache_ttl) → None` — Configura o provedor e resolve a URL base e os cabeçalhos de autenticação.
### `src/agent/providers/gemini.py`

**Propósito:** gemini — módulo do projeto.

- `gemini_contents(messages) → tuple[str | None, list[dict[str, Any]]]` — Separa a instrução de sistema e monta `contents` (papel `model` no lugar de `assistant`).
- `gemini_tools(tools) → list[dict[str, Any]] | None` — Converte o formato de ferramenta do Callidus (OpenAI) para `functionDeclarations`.
- `GeminiProvider` — Gemini (`/v1beta/models/{model}:generateContent`). A API não é compatível com OpenAI:.
- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `list_models(self, *, force) → list[str]` — Lista os modelos disponíveis na API, com cache curto.

- `_media_type(encoded) → str` — Deduz o tipo de mídia de uma imagem codificada em base64.
- `_image_part(encoded) → dict[str, Any]` — Monta a parte de imagem aceita pela API do Gemini.
- `_client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `_model_path(self, model_id) → str` — Normaliza o identificador do modelo para o caminho da API.
- `_body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da API do Gemini.
- `_parse(data) → tuple[str, list[ToolCall] | None, str | None]` — Extrai texto, chamadas de função e motivo de término da resposta do Gemini.
- `_chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API do Gemini.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela API do Gemini.

- `GeminiProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `GeminiProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `GeminiProvider._model_path(self, model_id) → str` — Normaliza o identificador do modelo para o caminho da API.
- `GeminiProvider.list_models(self, *, force) → list[str]` — Lista os modelos disponíveis na API, com cache curto.
- `GeminiProvider._body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da API do Gemini.
- `GeminiProvider._parse(data) → tuple[str, list[ToolCall] | None, str | None]` — Extrai texto, chamadas de função e motivo de término da resposta do Gemini.
- `GeminiProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API do Gemini.
- `GeminiProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela API do Gemini.

- `GeminiProvider.__init__(self, base_url, *, model, api_key, headers, timeout, max_retries, allow_private_hosts, verify_tls, models_cache_ttl) → None` — Configura o provedor e resolve a URL base e os cabeçalhos de autenticação.
### `src/agent/providers/http.py`

**Propósito:** http — módulo do projeto.

- `redact(text, secrets) → str` — Tira segredos de uma mensagem de log/erro: chaves explícitas e formatos conhecidos.
- `validate_base_url(url, *, allow_private_hosts) → str` — Valida a URL base de um provedor. Endereços privados só são recusados quando o operador.
- `HttpClientConfig` — Política HTTP comum: tempo limite, cabeçalhos, credencial e política de retry.
- `client_kwargs(config) → dict[str, Any]` — Argumentos de construção do `httpx.AsyncClient` (redirecionamento desligado por padrão).
- `map_http_error(exc, *, label, secrets, response) → ProviderError` — Converte exceção HTTP em erro de provedor com causa explícita (sem vazar credencial).
- `get_json(client, url, *, label, secrets, max_retries, backoff) → Any` — Executa um GET e devolve o corpo JSON.
- `post_json(client, url, body, *, label, secrets, max_retries, backoff) → Any` — Executa um POST e devolve o corpo JSON.
- `stream_lines(client, url, body, *, label, secrets) → Iterator[str]` — Linhas do corpo de uma resposta em streaming (JSON por linha ou SSE). Sem retry: uma.
- `sse_payloads(lines) → Iterator[str]` — Extrai o payload de eventos SSE (`data: ...`), ignorando comentários e linhas vazias.
- `resolved_base_url(self) → str` — URL base validada segundo a política de hosts privados.
- `resolved_headers(self) → dict[str, str]` — Cabeçalhos das requisições, com a credencial aplicada no cabeçalho configurado.
- `secrets(self) → list[str]` — Credenciais conhecidas, para serem removidas das mensagens de erro.
- `operation()` — Executa a requisição HTTP e devolve a resposta tipada do provedor.
- `operation()` — Executa a requisição HTTP e devolve a resposta tipada do provedor.

- `_is_private_address(host) → bool` — Indica se um endereço IP é interno (privado, loopback, link-local, reservado ou multicast).
- `_response_excerpt(response, limit) → str` — Trecho inicial do corpo da resposta, para compor mensagens de erro.
- `_retryable(exc) → bool` — Indica se o erro vale uma retentativa.
- `_with_retry(operation, *, label, secrets, max_retries, backoff)` — Executa uma operação HTTP repetindo apenas falhas transitórias.

- `HttpClientConfig.resolved_base_url(self) → str` — URL base validada segundo a política de hosts privados.
- `HttpClientConfig.resolved_headers(self) → dict[str, str]` — Cabeçalhos das requisições, com a credencial aplicada no cabeçalho configurado.
- `HttpClientConfig.secrets(self) → list[str]` — Credenciais conhecidas, para serem removidas das mensagens de erro.
### `src/agent/providers/openai_compatible.py`

**Propósito:** openai_compatible — módulo do projeto.

- `generation_body(generation) → dict[str, Any]` — Traduz os parâmetros de geração do Callidus para o corpo de uma API compatível com OpenAI.
- `response_format_body(response_format) → dict[str, Any] | None` — Aceita o formato do Callidus (`{"schema": {...}}`) e o formato nativo (`{"type": ...}`).
- `openai_message(message) → dict` — Converte uma mensagem do Callidus no formato de mensagem da OpenAI.
- `parse_tool_calls(message) → list[ToolCall] | None` — Extrai as chamadas de ferramenta de uma mensagem da OpenAI.
- `OpenAICompatibleProvider` — Adaptador para qualquer serviço que exponha o formato de `/v1/chat/completions` da OpenAI:.
- `capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `list_models(self, *, force) → list[str]` — Modelos disponíveis no serviço. Com `models_cache_ttl` a lista é cacheada em memória,.

- `_data_url(encoded) → str` — Monta a URL de dados de uma imagem base64.
- `_client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `_body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da API compatível com OpenAI.
- `_chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API compatível com OpenAI.
- `_chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela API compatível com OpenAI.

- `OpenAICompatibleProvider.capabilities(self) → ProviderCapabilities` — Recursos declarados pelo provedor.
- `OpenAICompatibleProvider._client(self) → httpx.AsyncClient` — Cliente HTTP configurado para o provedor.
- `OpenAICompatibleProvider.list_models(self, *, force) → list[str]` — Modelos disponíveis no serviço. Com `models_cache_ttl` a lista é cacheada em memória,.
- `OpenAICompatibleProvider._body(self, request) → dict` — Monta o corpo da requisição de inferência no formato da API compatível com OpenAI.
- `OpenAICompatibleProvider._chat(self, request) → ChatCompletionResponse` — Executa uma inferência completa pela API compatível com OpenAI.
- `OpenAICompatibleProvider._chat_streaming(self, request, on_delta) → ChatCompletionResponse` — Executa uma inferência em streaming pela API compatível com OpenAI.

- `OpenAICompatibleProvider.__init__(self, base_url, *, model, api_key, headers, timeout, max_retries, allow_private_hosts, verify_tls, name, models_cache_ttl) → None` — Configura o provedor e resolve a URL base e os cabeçalhos de autenticação.
### `src/agent/providers/openrouter.py`

**Propósito:** openrouter — módulo do projeto.

- `OpenRouterProvider` — OpenRouter fala o formato compatível com OpenAI (`/api/v1/chat/completions`) e acrescenta.

- `OpenRouterProvider.__init__(self, base_url, *, model, api_key, headers, timeout, max_retries, allow_private_hosts, verify_tls, referer, title, models_cache_ttl) → None` — Configura o provedor com os cabeçalhos opcionais de identificação do OpenRouter.
### `src/agent/providers/registry.py`

**Propósito:** registry — módulo do projeto.

- `ProviderSpec` — Descrição de um provedor no arquivo de configuração.
- `interpolate_text(text) → str` — Substitui `${VAR}` e `${VAR:-padrão}` pelo valor do ambiente.
- `parse_document(text, path) → dict[str, Any]` — Lê YAML ou JSON conforme a extensão do arquivo.
- `ProviderCatalog` — Provedores nomeados, carregados de um arquivo de configuração.
- `load_catalog(path) → ProviderCatalog` — Carrega o catálogo de provedores de um arquivo.
- `config_path_for_settings(settings) → Path` — Arquivo de provedores em uso: o configurado (`PROVIDERS_CONFIG_PATH`) ou o padrão da.
- `catalog_for_settings(settings) → ProviderCatalog` — Catálogo da configuração apontada nas settings (cacheado por arquivo e mtime).
- `resolve_api_key(spec, name) → str | None` — Chave do ambiente, arquivo de chave ou valor literal da configuração.
- `build_provider(name, spec, settings) → Any` — Instancia o provedor descrito pela especificação. Nenhuma credencial é impressa ou logada.
- `catalog_to_mapping(catalog) → dict[str, Any]` — Catálogo como mapa (o que vai para o arquivo de configuração).
- `save_catalog(catalog, path) → Path` — Grava o catálogo no arquivo (YAML ou JSON conforme a extensão) e invalida o cache.
- `build_builtin_provider(name, settings) → Any` — Provedores históricos, configurados por variável de ambiente (sem arquivo de configuração).
- `build_provider_by_name(name, settings) → Any` — Resolve um nome de provedor: primeiro o catálogo configurado, depois os provedores.
- `kind(self) → str` — Tipo do provedor normalizado em minúsculas.
- `replace(match) → str` — Substitui a configuração de um provedor, preservando a credencial.
- `from_mapping(cls, data) → ProviderCatalog` — Constrói o catálogo a partir do mapa lido do arquivo de configuração.
- `default_provider(self) → str | None` — Nome do provedor padrão declarado na configuração.
- `names(self) → list[str]` — Nomes dos provedores do catálogo.
- `get(self, name) → ProviderSpec | None` — Especificação de um provedor, quando existe.
- `spec(self, name) → ProviderSpec` — Especificação de um provedor, com erro explícito quando o nome não existe.
- `build(self, name, settings) → Any` — Instancia o provedor nomeado.

- `_interpolate(value) → Any` — Aplica a interpolação de ambiente em toda a estrutura da configuração.

- `ProviderSpec.kind(self) → str` — Tipo do provedor normalizado em minúsculas.
- `ProviderCatalog.from_mapping(cls, data) → ProviderCatalog` — Constrói o catálogo a partir do mapa lido do arquivo de configuração.
- `ProviderCatalog.default_provider(self) → str | None` — Nome do provedor padrão declarado na configuração.
- `ProviderCatalog.names(self) → list[str]` — Nomes dos provedores do catálogo.
- `ProviderCatalog.get(self, name) → ProviderSpec | None` — Especificação de um provedor, quando existe.
- `ProviderCatalog.spec(self, name) → ProviderSpec` — Especificação de um provedor, com erro explícito quando o nome não existe.
- `ProviderCatalog.build(self, name, settings) → Any` — Instancia o provedor nomeado.

- `ProviderCatalog.__init__(self, providers, default_provider) → None` — Cria o catálogo a partir de especificações já validadas.
### `src/agent/providers/secrets.py`

**Propósito:** secrets — módulo do projeto.

- `secret_path(settings, name) → Path` — Arquivo da credencial de um provedor. O nome do provedor vira nome de arquivo seguro.
- `write_secret(settings, name, secret) → Path` — Grava a credencial com permissão restrita (0600) e devolve o caminho.
- `read_secret(settings, name) → str | None` — Lê a credencial gravada de um provedor.
- `delete_secret(settings, name) → bool` — Remove a credencial gravada de um provedor.
- `secret_state(settings, name) → dict` — Situação da credencial sem revelar o valor.
- `is_world_readable(path) → bool` — A credencial não pode ficar legível por outros usuários do sistema.

### `src/agent/remote/__init__.py`

**Propósito:** __init__ — módulo do projeto.

### `src/agent/remote/ssh.py`

**Propósito:** ssh — módulo do projeto.

- `RemoteConfig` — Como alcançar o computador remoto do projeto.
- `RemoteError` — Falha ao falar com o servidor remoto.
- `CommandResult` — Desfecho de um comando remoto.
- `SshTransport` — Fala com o servidor pelo binário `ssh` do sistema (sem dependências extras).
- `target(self) → str` — Destino da conexão, no formato `usuario@host` quando há usuário.
- `is_windows(self) → bool` — Indica se o servidor remoto usa PowerShell.
- `run(self, command, *, cwd, timeout, on_output) → CommandResult` — Roda um comando no servidor remoto e devolve saída e código.
- `list_dir(self, path) → list[dict[str, Any]]` — Lista o conteúdo de uma pasta remota.
- `read_text(self, path) → str` — Lê um arquivo remoto como texto.
- `write_text(self, path, content) → int` — Grava um arquivo remoto, enviando o conteúdo em base64.
- `make_dir(self, path) → None` — Cria uma pasta remota (e os diretórios intermediários).
- `remove(self, path) → None` — Remove um arquivo ou pasta remoto, recursivamente.
- `move(self, source, target) → None` — Move ou renomeia um caminho no servidor remoto.
- `check(self) → dict[str, Any]` — Diagnóstico: o servidor responde? Qual o sistema?.
- `pump(stream, chunks, sink)` — Transfere os dados entre a sessão local e o canal remoto.

- `_resolve_key(key_path) → str | None` — Resolve o caminho da chave SSH privada, quando informada.
- `_host_preenchido(cls, value) → str` — Valida que o host do computador remoto foi informado.
- `_shell_conhecido(cls, value) → str` — Normaliza o shell do servidor para `posix` ou `powershell`.
- `_base_args(self) → list[str]` — Argumentos base da chamada ao `ssh`.
- `_quote(self, value) → str` — Cita um valor para o shell do servidor (POSIX ou PowerShell).
- `_remote_path(self, path) → str` — Junta a pasta remota do projeto com o caminho relativo.

- `RemoteConfig._host_preenchido(cls, value) → str` — Valida que o host do computador remoto foi informado.
- `RemoteConfig._shell_conhecido(cls, value) → str` — Normaliza o shell do servidor para `posix` ou `powershell`.
- `RemoteConfig.target(self) → str` — Destino da conexão, no formato `usuario@host` quando há usuário.
- `RemoteConfig.is_windows(self) → bool` — Indica se o servidor remoto usa PowerShell.
- `SshTransport._base_args(self) → list[str]` — Argumentos base da chamada ao `ssh`.
- `SshTransport._quote(self, value) → str` — Cita um valor para o shell do servidor (POSIX ou PowerShell).
- `SshTransport._remote_path(self, path) → str` — Junta a pasta remota do projeto com o caminho relativo.
- `SshTransport.run(self, command, *, cwd, timeout, on_output) → CommandResult` — Roda um comando no servidor remoto e devolve saída e código.
- `SshTransport.list_dir(self, path) → list[dict[str, Any]]` — Lista o conteúdo de uma pasta remota.
- `SshTransport.read_text(self, path) → str` — Lê um arquivo remoto como texto.
- `SshTransport.write_text(self, path, content) → int` — Grava um arquivo remoto, enviando o conteúdo em base64.
- `SshTransport.make_dir(self, path) → None` — Cria uma pasta remota (e os diretórios intermediários).
- `SshTransport.remove(self, path) → None` — Remove um arquivo ou pasta remoto, recursivamente.
- `SshTransport.move(self, source, target) → None` — Move ou renomeia um caminho no servidor remoto.
- `SshTransport.check(self) → dict[str, Any]` — Diagnóstico: o servidor responde? Qual o sistema?.

- `SshTransport.__init__(self, config) → None` — Monta o cliente SSH com a configuração do computador remoto.
### `src/agent/remote/tools.py`

**Propósito:** tools — módulo do projeto.

- `transport(ctx) → SshTransport` — Transporte SSH do contexto (o projeto tem computador remoto configurado).
- `read_file(ctx, args) → dict` — Lê uma janela de linhas de um arquivo remoto.
- `write_file(ctx, args) → dict` — Grava um arquivo remoto, criando as pastas intermediárias.
- `list_dir(ctx, args) → dict` — Lista o conteúdo de uma pasta remota.
- `edit_file(ctx, args) → dict` — Substitui um trecho de um arquivo remoto.
- `delete_file(ctx, args) → dict` — Remove um arquivo ou pasta remoto.
- `make_dir(ctx, args) → dict` — Cria uma pasta remota.
- `move_file(ctx, args) → dict` — Move ou renomeia um caminho remoto.
- `glob_files(ctx, args) → dict` — Busca arquivos remotos pelo nome.
- `search_grep(ctx, args) → dict` — Busca um padrão no conteúdo dos arquivos remotos.

- `_guard(ctx, path) → dict | None` — Mantém a trava de segurança: o caminho tem de ficar dentro do projeto.
### `src/agent/services/agent_scheduler.py`

**Propósito:** agent_scheduler — módulo do projeto.

- `SchedulerOperation` — Uma operação elegível (executar uma etapa, responder uma consulta, retomar um agente).
- `OperationResult` — Desfecho de uma operação. `ok=False` não interrompe a fila.
- `AgentScheduler` — Fila de operações elegíveis, executadas uma a uma.
- `age(self) → float` — Tempo que a operação espera na fila, em segundos.
- `as_dict(self) → dict[str, Any]` — Desfecho como dicionário serializável.
- `register(self, kind, handler) → None` — Registra quem executa um tipo de operação.
- `submit(self, kind, key, payload, *, priority) → bool` — Enfileira uma operação. `False` quando a mesma chave já está pendente.
- `pending_keys(self) → list[str]` — Chaves das operações pendentes.
- `stats(self) → dict[str, Any]` — Contadores da fila.
- `history(self, limit) → list[dict[str, Any]]` — Desfechos recentes das operações executadas.
- `execute(self, operation) → OperationResult` — Executa uma operação com tempo limite; erro não derruba a fila.
- `run_once(self) → OperationResult | None` — Executa a próxima operação elegível. `None` quando não há nada pendente.
- `run_forever(self) → None` — Laço principal. Dorme na fila — nenhuma inferência para procurar trabalho.
- `wait_idle(self, timeout) → bool` — Espera a fila esvaziar — sem consumir token. `True` se esvaziou no prazo.
- `stop(self) → None` — Interrompe o laço do escalonador.

- `_pick(self) → SchedulerOperation | None` — Retira a próxima operação, respeitando prioridade e tempo de espera.
- `_sync_idle(self) → None` — Marca o escalonador como ocioso quando não há pendências nem operação em curso.

- `SchedulerOperation.age(self) → float` — Tempo que a operação espera na fila, em segundos.
- `OperationResult.as_dict(self) → dict[str, Any]` — Desfecho como dicionário serializável.
- `AgentScheduler.register(self, kind, handler) → None` — Registra quem executa um tipo de operação.
- `AgentScheduler.submit(self, kind, key, payload, *, priority) → bool` — Enfileira uma operação. `False` quando a mesma chave já está pendente.
- `AgentScheduler.pending_keys(self) → list[str]` — Chaves das operações pendentes.
- `AgentScheduler.stats(self) → dict[str, Any]` — Contadores da fila.
- `AgentScheduler.history(self, limit) → list[dict[str, Any]]` — Desfechos recentes das operações executadas.
- `AgentScheduler._pick(self) → SchedulerOperation | None` — Retira a próxima operação, respeitando prioridade e tempo de espera.
- `AgentScheduler.execute(self, operation) → OperationResult` — Executa uma operação com tempo limite; erro não derruba a fila.
- `AgentScheduler.run_once(self) → OperationResult | None` — Executa a próxima operação elegível. `None` quando não há nada pendente.
- `AgentScheduler._sync_idle(self) → None` — Marca o escalonador como ocioso quando não há pendências nem operação em curso.
- `AgentScheduler.run_forever(self) → None` — Laço principal. Dorme na fila — nenhuma inferência para procurar trabalho.
- `AgentScheduler.wait_idle(self, timeout) → bool` — Espera a fila esvaziar — sem consumir token. `True` se esvaziou no prazo.
- `AgentScheduler.stop(self) → None` — Interrompe o laço do escalonador.

- `AgentScheduler.__init__(self, settings, *, operation_timeout_sec) → None` — Monta o escalonador com a sessão e a política de agentes.
### `src/agent/services/agent_service.py`

**Propósito:** agent_service — módulo do projeto.

- `AgentNotFoundError` — Agente inexistente.
- `AgentDepthError` — A delegação passaria do limite de profundidade configurado.
- `DiscardBlockedError` — Descartar o agente agora quebraria algo que ainda é necessário.
- `AgentService` — Operações sobre agentes lógicos e suas execuções.
- `get(self, agent_id) → AgentModel` — Agente por identificador.
- `find(self, agent_id) → AgentModel | None` — Agente por identificador, sem erro quando não existe.
- `agent_for_task(self, task_id) → AgentModel | None` — Agente associado a uma tarefa.
- `children(self, agent_id) → list[AgentModel]` — Delegados diretos de um agente.
- `descendants(self, agent_id) → list[AgentModel]` — Descendentes em ordem de profundidade (o mais perto primeiro).
- `ancestors(self, agent_id) → list[AgentModel]` — Cadeia de ancestrais, do mais distante para o mais próximo.
- `executions(self, agent_id) → list[AgentExecutionModel]` — Execuções de um agente, da mais antiga para a mais recente.
- `current_execution(self, agent_id) → AgentExecutionModel | None` — Execução viva ou recuperável do agente (a última em aberto).
- `ensure_agent(self, task_id, *, parent_agent_id, role, instructions) → AgentModel` — Agente da tarefa, criado se ainda não existir.
- `start_execution(self, agent_id, *, task_id, run_id, checkpoint) → AgentExecutionModel` — Abre uma execução do agente.
- `suspend(self, agent_id, *, reason, checkpoint) → AgentExecutionModel` — Suspende a execução: persiste o estado e libera o contexto de inferência.
- `resume(self, agent_id) → AgentExecutionModel` — Retoma a execução suspensa a partir do estado persistido.
- `wait_for_child(self, agent_id) → AgentExecutionModel` — A execução fica esperando uma resposta de descendente.
- `complete_execution(self, agent_id, *, result) → AgentExecutionModel` — Encerra a execução como concluída, gravando o resultado no checkpoint.
- `fail_execution(self, agent_id, error) → AgentExecutionModel` — Encerra a execução como falhada, guardando a causa.
- `cancel_execution(self, agent_id, *, reason) → AgentExecutionModel` — Cancela a execução em andamento.
- `save_checkpoint(self, agent_id, payload, *, merge) → AgentExecutionModel` — Grava o estado operacional da execução (etapa, plano, pendências, erros).
- `bound_checkpoint(self, checkpoint) → dict[str, Any]` — Mantém o checkpoint dentro do limite configurado.
- `checkpoint(self, agent_id) → dict[str, Any]` — Checkpoint atual do agente.
- `record_finding(self, agent_id, text, *, evidence, artifacts, kind) → dict[str, Any]` — Guarda uma descoberta do agente no estado persistente.
- `findings(self, agent_id) → list[dict[str, Any]]` — Descobertas registradas pelo agente.
- `record_task_result(self, task_id) → list[dict[str, Any]]` — Importa o resultado e as evidências de uma tarefa para o agente dela.
- `record_external_effect(self, agent_id, *, description, effect_id, resumable, verify_hint) → dict[str, Any]` — Registra um efeito externo (comando, sessão, transação) que a execução fez.
- `external_effects(self, agent_id) → list[dict[str, Any]]` — Efeitos externos registrados pelo agente.
- `effects_requiring_verification(self, agent_id) → list[dict[str, Any]]` — Efeitos externos que precisam ser verificados antes de a ação ser repetida.
- `mark_effect_verified(self, agent_id, effect_id) → dict[str, Any] | None` — Marca um efeito externo como verificado.
- `discard_checks(self, agent_id) → dict[str, Any]` — Verifica o que impede descartar o agente agora.
- `discard(self, agent_id, *, purge, reason, force) → dict[str, Any]` — Descarta o estado recuperável do agente.

- `_utcnow_iso() → str` — Instante atual em UTC, no formato ISO 8601.
- `_role_for_kind(kind) → str` — Papel do agente derivado do tipo da tarefa.
- `_set_agent_status(self, agent, target) → AgentModel` — Move o agente para um novo estado, validando a transição.
- `_set_execution_status(self, execution, target, error) → AgentExecutionModel` — Move a execução para um novo estado, validando a transição.

- `AgentService.get(self, agent_id) → AgentModel` — Agente por identificador.
- `AgentService.find(self, agent_id) → AgentModel | None` — Agente por identificador, sem erro quando não existe.
- `AgentService.agent_for_task(self, task_id) → AgentModel | None` — Agente associado a uma tarefa.
- `AgentService.children(self, agent_id) → list[AgentModel]` — Delegados diretos de um agente.
- `AgentService.descendants(self, agent_id) → list[AgentModel]` — Descendentes em ordem de profundidade (o mais perto primeiro).
- `AgentService.ancestors(self, agent_id) → list[AgentModel]` — Cadeia de ancestrais, do mais distante para o mais próximo.
- `AgentService.executions(self, agent_id) → list[AgentExecutionModel]` — Execuções de um agente, da mais antiga para a mais recente.
- `AgentService.current_execution(self, agent_id) → AgentExecutionModel | None` — Execução viva ou recuperável do agente (a última em aberto).
- `AgentService.ensure_agent(self, task_id, *, parent_agent_id, role, instructions) → AgentModel` — Agente da tarefa, criado se ainda não existir.
- `AgentService._set_agent_status(self, agent, target) → AgentModel` — Move o agente para um novo estado, validando a transição.
- `AgentService._set_execution_status(self, execution, target, error) → AgentExecutionModel` — Move a execução para um novo estado, validando a transição.
- `AgentService.start_execution(self, agent_id, *, task_id, run_id, checkpoint) → AgentExecutionModel` — Abre uma execução do agente.
- `AgentService.suspend(self, agent_id, *, reason, checkpoint) → AgentExecutionModel` — Suspende a execução: persiste o estado e libera o contexto de inferência.
- `AgentService.resume(self, agent_id) → AgentExecutionModel` — Retoma a execução suspensa a partir do estado persistido.
- `AgentService.wait_for_child(self, agent_id) → AgentExecutionModel` — A execução fica esperando uma resposta de descendente.
- `AgentService.complete_execution(self, agent_id, *, result) → AgentExecutionModel` — Encerra a execução como concluída, gravando o resultado no checkpoint.
- `AgentService.fail_execution(self, agent_id, error) → AgentExecutionModel` — Encerra a execução como falhada, guardando a causa.
- `AgentService.cancel_execution(self, agent_id, *, reason) → AgentExecutionModel` — Cancela a execução em andamento.
- `AgentService.save_checkpoint(self, agent_id, payload, *, merge) → AgentExecutionModel` — Grava o estado operacional da execução (etapa, plano, pendências, erros).
- `AgentService.bound_checkpoint(self, checkpoint) → dict[str, Any]` — Mantém o checkpoint dentro do limite configurado.
- `AgentService.checkpoint(self, agent_id) → dict[str, Any]` — Checkpoint atual do agente.
- `AgentService.record_finding(self, agent_id, text, *, evidence, artifacts, kind) → dict[str, Any]` — Guarda uma descoberta do agente no estado persistente.
- `AgentService.findings(self, agent_id) → list[dict[str, Any]]` — Descobertas registradas pelo agente.
- `AgentService.record_task_result(self, task_id) → list[dict[str, Any]]` — Importa o resultado e as evidências de uma tarefa para o agente dela.
- `AgentService.record_external_effect(self, agent_id, *, description, effect_id, resumable, verify_hint) → dict[str, Any]` — Registra um efeito externo (comando, sessão, transação) que a execução fez.
- `AgentService.external_effects(self, agent_id) → list[dict[str, Any]]` — Efeitos externos registrados pelo agente.
- `AgentService.effects_requiring_verification(self, agent_id) → list[dict[str, Any]]` — Efeitos externos que precisam ser verificados antes de a ação ser repetida.
- `AgentService.mark_effect_verified(self, agent_id, effect_id) → dict[str, Any] | None` — Marca um efeito externo como verificado.
- `AgentService.discard_checks(self, agent_id) → dict[str, Any]` — Verifica o que impede descartar o agente agora.
- `AgentService.discard(self, agent_id, *, purge, reason, force) → dict[str, Any]` — Descarta o estado recuperável do agente.

- `AgentService.__init__(self, session, settings) → None` — Cria o serviço ligado a uma sessão.
### `src/agent/services/cascade.py`

**Propósito:** cascade — módulo do projeto.

- `delete_cascade(session, root_table, root_id) → dict[str, int]` — Remove a linha e tudo que depende dela, na ordem segura (filhos antes dos pais).

- `_children_map() → dict[str, list[tuple[Any, str]]]` — Tabela pai → [(tabela filha, coluna filha)] segundo as chaves estrangeiras do modelo.
- `_scope(session, root_table, root_id) → dict[str, set]` — Conjunto de ids por tabela que descendem da linha raiz.
- `_deletion_order(scope) → list[str]` — Ordem topológica: cada tabela é apagada antes das tabelas que ela referencia.
### `src/agent/services/executor.py`

**Propósito:** executor — módulo do projeto.

- `ExecutorMetrics` — Contadores observáveis. Só mede o que o executor sabe de fato: tempos de espera e.
- `ExecutionSlot` — Uma inferência admitida. `waited_seconds` é o tempo parado na fila do executor.
- `InferenceExecutor` — Serializa as inferências do processo até o limite configurado.
- `get_executor(settings) → InferenceExecutor` — Executor compartilhado do processo. Cria no primeiro uso e ajusta o limite quando.
- `reset_executor() → None` — Descarta o executor do processo (isolamento de testes).
- `snapshot(self) → dict[str, Any]` — Métricas como dicionário, para exibição e diagnóstico.
- `limit(self) → int` — Limite atual de inferências simultâneas.
- `set_limit(self, limit) → None` — Muda o limite. A nova valer vale para as próximas aquisições.
- `acquire(self, *, purpose, provider, model) → ExecutionSlot` — Toma o slot de inferência. O chamador é responsável por `release()`.
- `release(self, *, error, slot) → None` — Devolve o slot. `error` distingue falha, cancelamento e sucesso.
- `metrics(self) → ExecutorMetrics` — Fotografia das métricas do executor.

- `_waiter(self, loop) → asyncio.Event` — Evento de espera associado a um laço de eventos.
- `_wake_all(self) → None` — Acorda todos os laços em espera (chamado quando um slot é devolvido).

- `ExecutorMetrics.snapshot(self) → dict[str, Any]` — Métricas como dicionário, para exibição e diagnóstico.
- `InferenceExecutor.limit(self) → int` — Limite atual de inferências simultâneas.
- `InferenceExecutor.set_limit(self, limit) → None` — Muda o limite. A nova valer vale para as próximas aquisições.
- `InferenceExecutor._waiter(self, loop) → asyncio.Event` — Evento de espera associado a um laço de eventos.
- `InferenceExecutor._wake_all(self) → None` — Acorda todos os laços em espera (chamado quando um slot é devolvido).
- `InferenceExecutor.acquire(self, *, purpose, provider, model) → ExecutionSlot` — Toma o slot de inferência. O chamador é responsável por `release()`.
- `InferenceExecutor.release(self, *, error, slot) → None` — Devolve o slot. `error` distingue falha, cancelamento e sucesso.
- `InferenceExecutor.metrics(self) → ExecutorMetrics` — Fotografia das métricas do executor.

- `InferenceExecutor.__init__(self, limit) → None` — Cria o executor com o limite de inferências simultâneas.
### `src/agent/services/query_service.py`

**Propósito:** query_service — módulo do projeto.

- `QueryRejectedError` — Consulta recusada: violaria uma regra do protocolo (ciclo, limite, alvo).
- `QueryService` — Consultas entre agentes: criação, resolução e correlação de respostas.
- `ask(self, requester_agent_id, target_agent_id, question, *, task_id, correlation_id, max_attempts) → AgentQueryModel` — Registra a pergunta do solicitante ao alvo.
- `get(self, query_id) → AgentQueryModel` — Consulta por identificador.
- `pending_for(self, agent_id) → list[AgentQueryModel]` — Consultas pendentes dirigidas a um agente.
- `queries_of(self, agent_id) → list[AgentQueryModel]` — Consultas em que um agente participa, como solicitante ou alvo.
- `answer_from_persisted(self, query) → dict[str, Any] | None` — Responde a partir do estado já persistido, sem reativar ninguém.
- `resolve(self, query_id, *, provider, profile) → AgentQueryModel` — Resolve a consulta: estado persistido primeiro, inferência só se faltar.
- `answer(self, query_id, answer, *, evidence, artifacts, uncertainty, answered_by_agent_id) → AgentQueryModel` — Registra a resposta de um agente a uma consulta (caminho sem inferência).
- `cancel(self, query_id, *, reason) → AgentQueryModel` — Cancela uma consulta pendente.

- `_declara_ausencia(texto) → bool` — O texto diz que não há evidência disponível?.
- `_sem_acento(text) → str` — Remove diacríticos.
- `_tokens(text) → set[str]` — Palavras úteis do texto, sem acentos, sem palavras vazias e sem as curtas demais.
- `_normalize(text) → str` — Normaliza o texto para comparação lexical.
- `_relevant(self, question, findings) → dict[str, Any] | None` — Descoberta persistida que responde à pergunta (busca lexical, sem inferência).
- `_context_for(self, agent, *, limit) → str` — Contexto mínimo do próprio agente: checkpoint e descoberta, sem transcrição.
- `_context_for_agents(self, agents, *, limit) → str` — Contexto de um conjunto de agentes, com atribuição de quem descobriu o quê.
- `_subtree_context(self, agent, *, limit) → str` — Estado do agente e de sua descendência.
- `_is_grounded(self, answer, agent) → tuple[bool, list[str]]` — A resposta da inferência encontra respaldo no estado persistido?.
- `_answer_with_inference(self, query, provider, profile) → dict[str, Any]` — Reativa o agente consultado e responde com uma inferência pelo executor compartilhado.
- `_remember_inference(self, agent, content, fundamentada) → None` — Guarda a resposta sintetizada como descoberta do agente consultado.

- `QueryService.ask(self, requester_agent_id, target_agent_id, question, *, task_id, correlation_id, max_attempts) → AgentQueryModel` — Registra a pergunta do solicitante ao alvo.
- `QueryService.get(self, query_id) → AgentQueryModel` — Consulta por identificador.
- `QueryService.pending_for(self, agent_id) → list[AgentQueryModel]` — Consultas pendentes dirigidas a um agente.
- `QueryService.queries_of(self, agent_id) → list[AgentQueryModel]` — Consultas em que um agente participa, como solicitante ou alvo.
- `QueryService._relevant(self, question, findings) → dict[str, Any] | None` — Descoberta persistida que responde à pergunta (busca lexical, sem inferência).
- `QueryService.answer_from_persisted(self, query) → dict[str, Any] | None` — Responde a partir do estado já persistido, sem reativar ninguém.
- `QueryService._context_for(self, agent, *, limit) → str` — Contexto mínimo do próprio agente: checkpoint e descoberta, sem transcrição.
- `QueryService._context_for_agents(self, agents, *, limit) → str` — Contexto de um conjunto de agentes, com atribuição de quem descobriu o quê.
- `QueryService._subtree_context(self, agent, *, limit) → str` — Estado do agente e de sua descendência.
- `QueryService.resolve(self, query_id, *, provider, profile) → AgentQueryModel` — Resolve a consulta: estado persistido primeiro, inferência só se faltar.
- `QueryService._is_grounded(self, answer, agent) → tuple[bool, list[str]]` — A resposta da inferência encontra respaldo no estado persistido?.
- `QueryService._answer_with_inference(self, query, provider, profile) → dict[str, Any]` — Reativa o agente consultado e responde com uma inferência pelo executor compartilhado.
- `QueryService._remember_inference(self, agent, content, fundamentada) → None` — Guarda a resposta sintetizada como descoberta do agente consultado.
- `QueryService.answer(self, query_id, answer, *, evidence, artifacts, uncertainty, answered_by_agent_id) → AgentQueryModel` — Registra a resposta de um agente a uma consulta (caminho sem inferência).
- `QueryService.cancel(self, query_id, *, reason) → AgentQueryModel` — Cancela uma consulta pendente.

- `QueryService.__init__(self, session, settings, *, agent_service) → None` — Cria o serviço ligado a uma sessão.
### `scripts/avaliar-consultas.py`

**Propósito:** avaliar-consultas — módulo do projeto.

- `montar_estado(tmp)` — Cria o projeto, a árvore de tarefas e os agentes, e persiste as descobertas usadas no gabarito.
- `main() → int` — Executa o gabarito contra o serviço de consultas e imprime o relatório de acertos.

### `scripts/build_brand_assets.py`

**Propósito:** build_brand_assets — módulo do projeto.

- `shapes(svg) → list[tuple[str, str, str]]` — Devolve [(tag, classe, conteúdo do atributo d/points)] na ordem do arquivo.
- `to_path(tag, cls, data) → str` — Converte a forma em um `<path>` com `d` equivalente.
- `write_svg(name, view_box, body, title) → None` — Grava o SVG final com o viewBox, o tamanho e o título informados.
- `main() → None` — Extrai as formas dos quatro SVG de origem e escreve os assets finais da marca.

### `scripts/medir-hierarquia.py`

**Propósito:** medir-hierarquia — módulo do projeto.

- `montar_cenario(tmp, niveis)` — Árvore de `niveis` gerações, cada uma com uma descoberta persistida.
- `main() → int` — Executa os três caminhos de medição e imprime o comparativo.

### `scripts/medir-ollama.py`

**Propósito:** medir-ollama — módulo do projeto.

- `rss_ollama_mb() → float` — RSS total (MB) dos processos `ollama` — a memória que o servidor de inferência usa.
- `modelo_carregado(base_url) → dict` — `GET /api/ps` — modelo residente e VRAM, se o backend informar.
- `main() → int` — Executa o cenário de medição contra o Ollama e imprime o relatório.

### `scripts/preencher_resume.py`

**Propósito:** preencher_resume — módulo do projeto.

- `secoes(texto) → dict[str, tuple[int, int]]` — Seções de arquivo do `resume.md` e seus limites de linha.
- `main(argv) → int` — Preenche as lacunas do `resume.md` e informa o que foi acrescentado.

- `_assinatura(no) → str` — Assinatura legível de uma função ou método.
- `_retorno(no) → str` — Tipo de retorno declarado, quando houver.
- `_primeira_linha(texto) → str` — Primeira linha útil de uma docstring.
- `_simbolos(caminho) → list[tuple[str, str, str]]` — Símbolos públicos de um arquivo Python, com a descrição de cada um.
- `_funcoes_js(caminho) → list[tuple[str, str, str]]` — Funções exportadas de um arquivo JavaScript, com a descrição do JSDoc.
- `_proposito_de(caminho) → str` — Propósito de um arquivo, lido do próprio documento ou do docstring do módulo.
- `_proposito_de_ativo(caminho) → str` — Propósito de um arquivo de asset (SVG, CSS, YAML, JSON).
- `_simbolos_por_arquivo(raiz) → dict[str, list[tuple[str, str, str]]]` — Símbolos de cada arquivo do inventário, indexados pelo caminho relativo.
- `_falta_simbolo(corpo, nome) → bool` — O símbolo já é citado no corpo da seção?.
### `web/static/assets/app/api.js`

**Propósito:** api — módulo do projeto.

- `api`
- `cleanError`
- `openRunStream`

### `web/static/assets/app/chat-scroll.js`

**Propósito:** chat-scroll — módulo do projeto.

- `createScrollFollow`
- `nearBottom`
- `setFollowing`
- `clearTimer`
- `cancelAutoScroll`
- `leaveBottom`
- `handleScroll`
- `handleWheel`
- `handleTouchStart`
- `handleTouchMove`
- `handleTouchEnd`
- `followContent`
- `scrollToBottom`
- `reset`
- `isFollowing`

### `web/static/assets/app/components/automations.js`

**Propósito:** automations — módulo do projeto.

- `definition`
- `submit`
- `act`
- `open`
- `remove`
- `stateLabel`
- `when`

### `web/static/assets/app/components/chat.js`

**Propósito:** chat — módulo do projeto.

- `isOpen`
- `toggleEntry`
- `isTurnCollapsed`
- `toggleTurn`
- `insideNestedScroller`
- `onScroll`
- `onWheel`
- `onTouchStart`
- `onTouchMove`
- `onTouchEnd`
- `scrollToBottom`
- `onProviderChange`
- `onSend`
- `onKeydown`
- `onFiles`
- `readAsBase64`
- `removeAttachment`

### `web/static/assets/app/components/details.js`

**Propósito:** details — módulo do projeto.

- `selectTab`

### `web/static/assets/app/components/live.js`

**Propósito:** live — módulo do projeto.

- `onClick`
- `onSearch`
- `bump`

### `web/static/assets/app/components/palette.js`

**Propósito:** palette — módulo do projeto.

- `close`
- `run`
- `onKeydown`
- `newConversation`
- `toggleTheme`

### `web/static/assets/app/components/providers.js`

**Propósito:** providers — módulo do projeto.

- `typeInfo`
- `startNew`
- `edit`
- `onTypeChange`
- `entryFromForm`
- `save`
- `remove`
- `makeDefault`
- `test`
- `fetchModels`
- `clearSecret`

### `web/static/assets/app/components/settings.js`

**Propósito:** settings — módulo do projeto.

- `ensureModels`
- `startRename`
- `confirmRename`
- `showRemote`
- `pickFolder`

### `web/static/assets/app/components/sidebar.js`

**Propósito:** sidebar — módulo do projeto.

### `web/static/assets/app/components/topbar.js`

**Propósito:** topbar — módulo do projeto.

- `activateBranch`

### `web/static/assets/app/live-state.js`

**Propósito:** live-state — módulo do projeto.

- `category`
- `cap`
- `tailText`
- `emptyMetrics`
- `createState`
- `newOp`
- `newOutput`
- `insertSorted`
- `parseTs`
- `recordLatency`
- `applyEvent`
- `reduce`
- `findLast`
- `criterionText`
- `reduceRun`
- `reduceTask`
- `reduceAgent`
- `trimOutputs`
- `reduceOp`
- `trimOps`
- `applyLive`
- `markConnection`
- `markResync`
- `currentTask`
- `elapsedSeconds`
- `latency`
- `sortTasks`
- `buildTree`
- `subtreeIds`
- `matches`
- `visibleEvents`
- `scoped`
- `outputsList`
- `terminalList`
- `toolList`
- `filesList`
- `verificationList`
- `countsText`
- `progressText`
- `describe`

### `web/static/assets/app/live-stream.js`

**Propósito:** live-stream — módulo do projeto.

- `createStream`
- `open`
- `stop`

### `web/static/assets/app/live-view.js`

**Propósito:** live-view — módulo do projeto.

- `esc`
- `clock`
- `duration`
- `taskTitle`
- `statusBadge`
- `renderHeader`
- `renderFilters`
- `treeNode`
- `renderTree`
- `renderTaskHistory`
- `renderActivity`
- `renderOutputs`
- `renderTerminal`
- `summaryText`
- `renderTools`
- `renderFiles`
- `renderVerification`
- `renderMetrics`
- `renderInterrupted`

### `web/static/assets/app/main.js`

**Propósito:** main — módulo do projeto.

- `isTyping`
- `onGlobalKey`
- `newProject`
- `createProject`
- `openFolder`
- `pickFolderForProject`
- `openRemote`
- `saveRemoteConfig`
- `checkRemote`
- `removeRemote`
- `createFolder`
- `browse`
- `useFolder`
- `moveFolderTo`
- `renameConversation`

### `web/static/assets/app/tools-report.js`

**Propósito:** resumir ferramentas, dependências ausentes, diagnóstico e skills para a aba Ferramentas.

- `formatToolsReport(report)` — Monta o texto da aba a partir das respostas de `/tools`, `/tools/availability`, `/system/diagnose` e `/skills`.

### `web/static/assets/app/store.js`

**Propósito:** store — módulo do projeto.

- `toast`
- `workspaceId`
- `roots`
- `childrenOf`
- `descendantIds`
- `setTheme`
- `setDensity`
- `watchViewport`
- `openView`
- `bootstrap`
- `loadRemote`
- `saveRemote`
- `clearRemote`
- `testRemote`
- `renameProject`
- `moveProject`
- `deleteProject`
- `conversationStatus`
- `loadProviders`
- `selectProject`
- `selectConversation`
- `deleteConversation`
- `refreshTasks()` — Recarrega tarefas da conversa ou projeto e chama `hydrateFeedsFromHistory()` para repor feeds a partir de `/observe`.
- `hydrateFeedsFromHistory()` — Para cada mensagem raiz sem feed em memória, reaplica eventos da run mais recente (`replayFeedFromRun`).
- `replayFeedFromRun(runId, rootId)` — Rejoga eventos de `/observe` no feed da mensagem raiz (dedupe por `eventId` em `pushActivity`).
- `refreshRun`
- `runConfig`
- `sendMessage`
- `startRun`
- `stepRun`
- `autoRun`
- `flushQueue`
- `cancelQueued`
- `setAutoMode`
- `pauseRun`
- `resumeRun`
- `cancelRun`
- `connectStream`
- `startTaskPolling`
- `stopTaskPolling`
- `disconnectStream`
- `selectTask`
- `loadInspector`
- `loadDiff`
- `loadMetrics`
- `loadGraph`
- `loadTools`
- `discoverMcp`
- `rootIdOf`
- `pushActivity`
- `loadModels`
- `testProvider`
- `saveProviderConfig`
- `removeProvider`
- `setProviderSecret`
- `clearProviderSecret`
- `loadAutomations`
- `loadAutomationDetail`
- `createAutomation`
- `automationAction`
- `deleteAutomation`
- `loadSupervisorStatus`

### `web/static/assets/app/ui.js`

**Propósito:** ui — módulo do projeto.

- `icon`
- `escapeHtml`
- `renderMarkdown`
- `isListItem`
- `isTableRow`
- `isTableSeparator`
- `splitTableRow`
- `renderList`
- `level`
- `inline`
- `stamp`
- `ago`
- `toolOf`
- `titleOf`
- `statusLabel`
- `modelLabel`
- `plural`
- `toolArgsSummary`
- `describeActivity`
- `integrateNarrative(activity)` — Acopla entradas narrativas (`work.explained`, pensamento) ao item operacional seguinte; narração residual vai para a última operação ou vira linha `narrative` dentro de `activity-items`. Entrada: feed descrito; saída: linhas com campo opcional `narrations`.
- `splitFeed(activity)` — Classifica entradas em narrativas vs operações (legado/testes). Saída: `{narrative, operations}`.
- `summarizeActivity`
- `diffLines`

### `.pytest_cache/README.md`

**Propósito:** This directory contains data from the pytest's cache plugin,.

### `data/debug-e2e/workspace/calc.py`

**Propósito:** Documento do projeto..

### `data/debug-e2e/workspace/tests/test_calc.py`

**Propósito:** Documento do projeto..

### `docs/architecture/automacoes.md`

**Propósito:** Voltar ao [Hub](/docs/architecture/README.md) · [Modelo de dados](/docs/architecture/modelo-dados.md) · [Execução autônoma](/docs/architecture/execucao-autonoma.md).

### `docs/architecture/avaliacao.md`

**Propósito:** A avaliação reproduzível com critérios objetivos de aceite.

### `docs/architecture/ciclo-ferramentas.md`

**Propósito:** O ciclo de inspeção com ferramentas antes da resposta do modelo.

### `docs/architecture/execucao-remota.md`

**Propósito:** O projeto rodando em outro computador, por SSH.

### `docs/architecture/hierarquia-agentes.md`

**Propósito:** Voltar ao [Hub](/docs/architecture/README.md) · [Visão geral](/docs/architecture/visao-geral.md) · [Provedores](/docs/architecture/provedores.md).

### `docs/architecture/provedores.md`

**Propósito:** Voltar ao [Hub](/docs/architecture/README.md) · Código: [`src/agent/providers/`](/src/agent/providers/README.md).

### `docs/regras/marca.md`

**Propósito:** **Regra:** o projeto se chama **Callidus**. Toda interface, documentação, metadado de API e mensagem de usuário usa o nome "Callidus" e o símbolo oficial. Termos genéricos em português ("o agente", "o runtime") continuam valendo como substantivo comum — não são nome de produto.

### `internal/tarefas/2026-10-17-complemento-regras-operacionais.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-17-diagramas-dimensoes-verificacao.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-17-nucleo-agente-fase0-1.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-17-repositorio-local.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-18-evolucao-arquitetural.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-18-observabilidade-tempo-real.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-18-validacao-verificacao-progresso.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-19-evolucao-skills-decomposicao-execucao.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-19-rebrand-callidus.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-20-automacoes-persistentes.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-20-hierarquia-agentes-executor.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/2026-10-20-remodelagem-arquitetural.md`

**Propósito:** | Campo | Valor |.

### `internal/tarefas/_modelo-checklist.md`

**Propósito:** O modelo de checklist usado por toda atividade do projeto.

### `lab/avaliar.py`

**Propósito:** Avaliação reproduzível do Callidus com o modelo local de referência.

### `lab/out/baseline-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/baseline-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/diag1-root/check_verification.py`

**Propósito:** Documento do projeto..

### `lab/out/diag1-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/diag1-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/diag2-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/diag2-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed10-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed10-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed11-root/README.md`

**Propósito:** Este é o README do projeto Callidus.

### `lab/out/fixed11-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed11-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed12-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed12-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed13-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed13-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed14-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed14-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed15-root/answer.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed15-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed15-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed16-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed16-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed17-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed17-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed18-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed18-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed19-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed19-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed3-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed3-root/structure.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed3-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed4-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed4-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed5-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed5-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed6-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed6-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed7-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed7-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed8-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed8-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/out/fixed9-root/src/main.js`

**Propósito:** Documento do projeto..

### `lab/out/fixed9-root/tests/test_frontend.py`

**Propósito:** Documento do projeto..

### `lab/run_scenario.py`

**Propósito:** Cenário controlado: reproduz a última conversa real ("continue") com gpt-oss:20b.

### `src/agent/automation/README.md`

**Propósito:** Automações persistentes, autônomas e multiplataforma: o Callidus planeja, grava,.

### `src/agent/remote/README.md`

**Propósito:** Transporte das ações de um projeto (comandos, leituras, escritas) quando o projeto roda em.

### `tests/conftest.py`

**Propósito:** Arquivo: tests/conftest.py.

### `tests/fixtures/README.md`

**Propósito:** Projetos de exemplo usados pelos testes de ponta a ponta.

### `tests/fixtures/sample_project/calc.py`

**Propósito:** Documento do projeto..

### `tests/fixtures/sample_project/tests/test_calc.py`

**Propósito:** Documento do projeto..

### `tests/test_agent_api.py`

**Propósito:** Arquivo: tests/test_agent_api.py.

### `tests/test_agent_hierarchy_e2e.py`

**Propósito:** Arquivo: tests/test_agent_hierarchy_e2e.py.

### `tests/test_agent_resilience.py`

**Propósito:** Arquivo: tests/test_agent_resilience.py.

### `tests/test_agent_scheduler.py`

**Propósito:** Arquivo: tests/test_agent_scheduler.py.

### `tests/test_agent_service.py`

**Propósito:** Arquivo: tests/test_agent_service.py.

### `tests/test_anthropic_provider.py`

**Propósito:** Arquivo: tests/test_anthropic_provider.py.

### `tests/test_api_smoke.py`

**Propósito:** Arquivo: tests/test_api_smoke.py.

### `tests/test_automation_api.py`

**Propósito:** Arquivo: tests/test_automation_api.py.

### `tests/test_automation_end_to_end.py`

**Propósito:** Arquivo: tests/test_automation_end_to_end.py.

### `tests/test_automation_platforms.py`

**Propósito:** Arquivo: tests/test_automation_platforms.py.

### `tests/test_automation_runtime.py`

**Propósito:** Arquivo: tests/test_automation_runtime.py.

### `tests/test_brand.py`

**Propósito:** Arquivo: tests/test_brand.py.

### `tests/test_context_requirements.py`

**Propósito:** Arquivo: tests/test_context_requirements.py.

### `tests/test_execution_package.py`

**Propósito:** Arquivo: tests/test_execution_package.py.

### `tests/test_executor_scope.py`

**Propósito:** Arquivo: tests/test_executor_scope.py.

### `tests/test_gemini_provider.py`

**Propósito:** Arquivo: tests/test_gemini_provider.py.

### `tests/test_http_transport.py`

**Propósito:** Arquivo: tests/test_http_transport.py.

### `tests/test_inference_executor.py`

**Propósito:** Arquivo: tests/test_inference_executor.py.

### `tests/test_llamacpp_remote.py`

**Propósito:** Arquivo: tests/test_llamacpp_remote.py.

### `tests/test_model_tool_operation.py`

**Propósito:** Arquivo: tests/test_model_tool_operation.py.

### `tests/test_ollama_provider.py`

**Propósito:** Arquivo: tests/test_ollama_provider.py.

### `tests/test_openai_compatible_provider.py`

**Propósito:** Arquivo: tests/test_openai_compatible_provider.py.

### `tests/test_openrouter_provider.py`

**Propósito:** Arquivo: tests/test_openrouter_provider.py.

### `tests/test_plan_contract.py`

**Propósito:** Arquivo: tests/test_plan_contract.py.

### `tests/test_project_delete.py`

**Propósito:** Arquivo: tests/test_project_delete.py.

### `tests/test_provider_config_api.py`

**Propósito:** Arquivo: tests/test_provider_config_api.py.

### `tests/test_provider_security.py`

**Propósito:** Arquivo: tests/test_provider_security.py.

### `tests/test_provider_selection.py`

**Propósito:** Arquivo: tests/test_provider_selection.py.

### `tests/test_providers_api.py`

**Propósito:** Arquivo: tests/test_providers_api.py.

### `tests/test_providers_registry.py`

**Propósito:** Arquivo: tests/test_providers_registry.py.

### `tests/test_query_service.py`

**Propósito:** Arquivo: tests/test_query_service.py.

### `tests/test_recovery_policy.py`

**Propósito:** verificar a decisão de continuar, investigar uma vez, pausar por orçamento ou recusar replanejamento quando a falha pede ação externa.

### `tests/test_recovery_and_reporting.py`

**Propósito:** Arquivo: tests/test_recovery_and_reporting.py.

### `tests/test_remote_ssh.py`

**Propósito:** Arquivo: tests/test_remote_ssh.py.

### `tests/test_request_permissions.py`

**Propósito:** Arquivo: tests/test_request_permissions.py.

### `tests/test_tool_loop.py`

**Propósito:** Arquivo: tests/test_tool_loop.py.

### `tests/test_truncated_output.py`

**Propósito:** Arquivo: tests/test_truncated_output.py.

### `tests/test_verification_integrity.py`

**Propósito:** Arquivo: tests/test_verification_integrity.py.

### `tests/test_web_frontend.py`

**Propósito:** Documento do projeto..

### `tests/web/chat-scroll.test.mjs`

**Propósito:** Documento do projeto..

### `.cursor/resume-inventario.json`

**Propósito:** Configuração de runtime do Callidus..

### `data/providers.yaml`

**Propósito:** Exemplo de configuração de provedores (modelo de referência)..

### `lab/out/avaliacao-antes.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/avaliacao-depois.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/avaliacao-depois2.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/baseline-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/baseline.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/diag1-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/diag1.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/diag2-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/diag2.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed10-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed10.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed11-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed11.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed12-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed12.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed13-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed13.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed14-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed14.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed15-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed15.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed16-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed16.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed17-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed17.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed18-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed18.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed19-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed3-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed3.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed4-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed4.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed5-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed5.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed6-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed6.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed7-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed7.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed8-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed8.json`

**Propósito:** Configuração de runtime do Callidus..

### `lab/out/fixed9-root/src/styles.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `lab/out/fixed9.json`

**Propósito:** Configuração de runtime do Callidus..

### `media/Callidus Logo.svg`

**Propósito:** Recurso visual da marca..

### `media/Callidus Name + Logo Horizontal.svg`

**Propósito:** Logotipo em texto da marca (fonte)..

### `media/Callidus Name + Logo Vertical.svg`

**Propósito:** Logotipo em texto da marca (fonte)..

### `media/Callidus Name.svg`

**Propósito:** Logotipo em texto da marca (fonte)..

### `providers.example.yaml`

**Propósito:** Exemplo de configuração de provedores (modelo de referência)..

### `web/static/assets/app/style.css`

**Propósito:** Folha de estilo da interface (design system, temas e layout)..

### `web/static/assets/brand/callidus-lockup-vertical.svg`

**Propósito:** Logotipo vertical da marca (fonte)..

### `web/static/assets/brand/callidus-lockup.svg`

**Propósito:** Recurso visual da marca..

### `web/static/assets/brand/callidus-mark-current.svg`

**Propósito:** Símbolo da marca (fonte)..

### `web/static/assets/brand/callidus-mark.svg`

**Propósito:** Símbolo da marca (fonte)..

### `web/static/assets/brand/callidus-wordmark.svg`

**Propósito:** Logotipo em texto da marca (fonte)..

### `web/static/assets/brand/favicon.svg`

**Propósito:** Ícone de aba do navegador..

### `internal/tarefas/2026-10-20-auditoria-documentacao.md`

**Propósito:** | Campo | Valor |.


### `media/icons/alerta.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/ativos-visuais.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/autoaperfeicoamento.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/checklist.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/commits.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/documentacao.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/hub.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/mcp.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/navegacao.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/organizacao.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/principios.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/projeto.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/tarefas.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/validacoes.svg`

**Propósito:** Recurso visual da marca..


### `media/icons/verificacao.svg`

**Propósito:** Recurso visual da marca..

### `lab/demo_app.py`

**Propósito:** aplicativo de demonstração que o Callidus abre, acompanha e inspeciona em teste real.. camada de laboratório — processo descartável que escreve um sinal de vida e serve HTTP local.

- `_Handler(BaseHTTPRequestHandler)` — Responde a uma rota de estado, para que a verificação do resultado seja real.
- `_Handler.do_GET() -> None` — Devolve o estado do aplicativo em JSON.
- `_Handler.log_message(fmt: str, *args) -> None` — Silencia o log de acesso: o aplicativo é silencioso por padrão.
- `_write_heartbeat(out: Path, payload: dict) -> None` — Grava o sinal de vida do aplicativo.
- `main(argv: list[str] | None=None) -> int` — Executa o aplicativo de demonstração.
### `src/agent/desktop/__init__.py`

**Propósito:** expor a automação de desktop (tela, entrada, janelas e acessibilidade) com uma interface única.. camada de infraestrutura — ponto de entrada estável para o agente.

### `src/agent/desktop/README.md`

**Propósito:** Índice da automação de desktop: tela, janelas, entrada e árvore de acessibilidade.

### `src/agent/desktop/accessibility.py`

**Propósito:** consultar a árvore de acessibilidade e agir sobre um elemento pelo nome, relendo a geometria na hora.

- `parse_accessibility_text(text: str) -> dict[str, Any]` — Interpreta o texto estável dos adaptadores (janela e elementos).
- `match_elements(elements: list[dict[str, Any]], name: str) -> list[dict[str, Any]]` — Filtra elementos cujo nome contém o texto pedido.
- `element_center(element: dict[str, Any]) -> tuple[int, int] | None` — Centro do retângulo, ou `None` quando a área é vazia.
- `list_elements(app: str | None=None, *, limit: int=40) -> dict[str, Any]` — Lista os elementos da janela em foco pela API nativa da plataforma.
- `wait_for(*, title: str='', name: str='', timeout: float=8.0, interval: float=0.4) -> dict[str, Any]` — Espera uma janela ou um elemento, com tempo limitado.
- `click_named(name: str, *, app: str | None=None, button: str='left') -> dict[str, Any]` — Clica no centro de um elemento localizado pelo nome.
- `_bounds(parts: list[str]) -> dict[str, int] | None` — Converte quatro números textuais em um retângulo.
- `_clean_app(app: str | None) -> str | None | dict[str, Any]` — Normaliza o nome do aplicativo ou devolve erro de formato.
- `_run(command: list[str], timeout: float) -> subprocess.CompletedProcess` — Executa o comando nativo da plataforma.
- `_from_command(command: list[str], *, timeout: float) -> dict[str, Any]` — Roda o adaptador e interpreta a saída, com dica de permissão.
- `_macos_script(app: str | None, limit: int) -> list[str]` — AppleScript que lista os elementos da primeira janela.
- `_windows_script(app: str | None, limit: int) -> str` — PowerShell que lista os filhos da janela em foco via UI Automation.
- `_linux_elements(app: str | None, limit: int) -> dict[str, Any]` — Lista elementos via AT-SPI quando `pyatspi` está instalado.
### `src/agent/desktop/capabilities.py`

**Propósito:** descrever a tela do computador e capturar screenshots de tela inteira ou de região.. camada de infraestrutura — geometria da tela e captura de imagem por plataforma.

- `_run(command: list[str], timeout: float=30) -> subprocess.CompletedProcess` — Executa um comando do sistema capturing a saída.
- `_macos_screen() -> dict[str, Any]` — Geometria da tela no macOS, lida do desktop do Finder.
- `_windows_screen() -> dict[str, Any]` — Geometria da tela no Windows, lida das telas do Windows Forms.
- `_linux_screen() -> dict[str, Any]` — Geometria da tela no Linux, lida do `xrandr` (X11) ou dos portals (Wayland).
- `screen_info() -> dict[str, Any]` — Informa a geometria da tela e o que é possível fazer com ela.
- `_capture_target(path: str | None) -> str` — Resolve o caminho de destino da captura.
- `capture_screenshot(path: str | None=None, region: dict[str, int] | None=None) -> dict[str, Any]` — Captura a tela inteira ou uma região permitida.
### `src/agent/desktop/input.py`

**Propósito:** injetar eventos de mouse e teclado na sessão gráfica do usuário.. camada de infraestrutura — cliques, digitação, teclas e rolagem por plataforma.

- `_run(command: list[str], timeout: float=20) -> subprocess.CompletedProcess` — Executa um comando do sistema capturing a saída.
- `_check_point(x: int, y: int) -> dict[str, Any] | None` — Confere se um ponto está dentro da tela conhecida.
- `_macos_click(x: int, y: int, *, double: bool=False, button: str='left') -> dict[str, Any]` — Clica por coordenadas no macOS, via AppleScript do System Events.
- `_windows_click(x: int, y: int, *, double: bool=False, button: str='left') -> dict[str, Any]` — Clica por coordenadas no Windows, via `user32` do PowerShell.
- `_linux_click(x: int, y: int, *, double: bool=False, button: str='right') -> dict[str, Any]` — Clica por coordenadas no Linux, via `xdotool`.
- `click(x: int, y: int, *, double: bool=False, button: str='left') -> dict[str, Any]` — Clica em um ponto da tela.
- `drag(x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]` — Arrasta o ponteiro de um ponto a outro.
- `press_key(key: str, *, repeat: int=1) -> dict[str, Any]` — Pressiona uma tecla ou um atalho de teclado.
- `_windows_keys(name: str) -> str` — Converte um nome de tecla para a notação do SendKeys.
- `type_text(text: str, *, interval: float=0.01) -> dict[str, Any]` — Digita um texto na janela em foco.
- `_ps_quote(value: str) -> str` — Cita um texto para uso dentro de um comando PowerShell.
- `scroll(amount: int, *, horizontal: bool=False) -> dict[str, Any]` — Rola a tela.
### `src/agent/desktop/windows.py`

**Propósito:** listar janelas ativas, títulos e aplicativos donos das janelas.. camada de infraestrutura — inventário de janelas por plataforma.

- `WindowInfo` — Uma janela visível da sessão gráfica.
- `WindowInfo.as_dict() -> dict[str, Any]` — Representação serializável da janela.
- `_run(command: list[str], timeout: float=25) -> subprocess.CompletedProcess` — Executa um comando do sistema capturing a saída.
- `_macos_windows() -> tuple[list[WindowInfo], str | None]` — Janelas do macOS, lidas do System Events.
- `_windows_windows() -> tuple[list[WindowInfo], str | None]` — Janelas do Windows, lidas dos processos com título de janela.
- `_linux_windows() -> tuple[list[WindowInfo], str | None]` — Janelas do Linux, lidas do `wmctrl` (X11) ou do Wayland, quando disponível.
- `list_windows(match: str | None=None, limit: int=50) -> dict[str, Any]` — Lista as janelas visíveis da sessão gráfica.
### `src/agent/engineering/__init__.py`

**Propósito:** expor a caixa de ferramentas de engenharia de software do agente.. camada de infraestrutura — ponto de entrada estável para o agente.

### `src/agent/engineering/README.md`

**Propósito:** Índice da descoberta de projeto, da leitura do Git e das verificações de qualidade.
### `src/agent/engineering/discovery.py`

**Propósito:** identificar a linguagem, as ferramentas e os comandos de um projeto real.. camada de infraestrutura — leitura de manifests e derivação dos comandos de build, lint e teste.

- `ProjectInfo` — O que a descoberta encontrou sobre um projeto.
- `ProjectInfo.as_dict() -> dict[str, Any]` — Representação serializável da descoberta.
- `_safe_read_json(path: Path) -> dict[str, Any]` — Lê um JSON sem quebrar a descoberta quando o arquivo está malformado.
- `_safe_read_toml(path: Path) -> dict[str, Any]` — Lê um TOML sem quebrar a descoberta quando o arquivo está malformado.
- `manifest_keys(name: str) -> tuple[str, str]` — Linguagem e gerenciador associados a um manifest.
- `read_manifest(path: str | Path) -> dict[str, Any]` — Lê um manifest de projeto e devolve seus campos de alto nível.
- `detect_project(root: str | Path) -> ProjectInfo` — Analisa um diretório e descreve o projeto encontrado.
- `_count_packages(base: Path) -> int` — Conta os pacotes de um monorepo.
- `_node_runner(base: Path) -> str` — Descobre o gerenciador de pacotes JavaScript do projeto.
- `discover_commands(root: str | Path) -> dict[str, Any]` — Deriva os comandos de build, lint, teste e execução do projeto.
### `src/agent/engineering/git.py`

**Propósito:** inspecionar o repositório Git: estado, branch, histórico e diferenças.. camada de infraestrutura — leitura do repositório sem alterar o trabalho do usuário.

- `_run(root: str | Path, args: list[str]) -> subprocess.CompletedProcess` — Executa um comando Git na pasta do projeto.
- `is_repository(root: str | Path) -> bool` — Indica se a pasta é um repositório Git.
- `git_status(root: str | Path) -> dict[str, Any]` — Estado do repositório: arquivos modificados, staged e não rastreados.
- `git_branch(root: str | Path) -> dict[str, Any]` — Branches do repositório, com a branch atual em destaque.
- `git_log(root: str | Path, limit: int=20, path: str | None=None) -> dict[str, Any]` — Histórico recente de commits.
- `git_diff(root: str | Path, *, staged: bool=False, path: str | None=None, stat: bool=True) -> dict[str, Any]` — Diferenças do repositório.
### `src/agent/engineering/quality.py`

**Propósito:** executar verificações de qualidade (lint, teste, build) e resumir o resultado.. camada de infraestrutura — execução de comandos de projeto e leitura do resultado.

- `parse_pytest_summary(output: str) -> dict[str, Any]` — Lê o resumo do pytest na saída do comando.
- `parse_generic_errors(output: str) -> dict[str, Any]` — Conta sinais de erro em uma saída de compilação ou teste.
- `summarize_test_output(output: str, exit_code: int) -> dict[str, Any]` — Resume o resultado de uma execução de testes.
- `run_check(command: Sequence[str], *, cwd: str | Path | None=None, timeout: float=300.0, env: dict[str, str] | None=None) -> dict[str, Any]` — Executa um comando de qualidade e devolve o resultado interpretado.
### `src/agent/skills/authoring/__init__.py`

**Propósito:** expor a infraestrutura de autoria, ciclo de vida e versionamento de skills.. camada de aplicação — fachada pública do pacote `agent.skills.authoring`.
### `src/agent/skills/authoring/layout.py`

**Propósito:** definir a estrutura de pasta, o `SKILL.md` e o `manifest.json` de uma skill autoral.. camada de aplicação — contrato de formato das skills criadas pelo agente.

- `now_iso() -> str` — Instante atual em ISO 8601, com fuso horário.
- `SkillLayout` — As pastas e os arquivos que compõem uma skill.
- `SkillLayout.of(root: str | Path) -> SkillLayout` — Monta o layout a partir da pasta da skill.
- `SkillLayout.ensure() -> SkillLayout` — Cria a pasta da skill e as subpastas opcionais.
- `SkillLayout.as_dict() -> dict[str, Any]` — Representação serializável do layout.
- `skill_dir(root: str | Path, name: str) -> Path` — Caminho da pasta de uma skill dentro de um repositório de skills.
- `render_skill_md(name: str, description: str, *, version: str='1.0.0', activation: list[str] | None=None, prohibited: list[str] | None=None, tools: list[str] | None=None, procedures: list[str] | None=None, validation: list[str] | None=None, risks: list[str] | None=None, prerequisites: list[str] | None=None, error_handling: list[str] | None=None) -> str` — Gera o `SKILL.md` de uma skill nova.
- `default_manifest(name: str, *, version: str='1.0.0', description: str='', origin: str='agent', state: str='draft', permissions: list[str] | None=None, requires_tools: list[str] | None=None, requires_binaries: list[str] | None=None) -> dict[str, Any]` — Manifesto inicial de uma skill.
- `render_manifest(manifest: dict[str, Any]) -> str` — Serializa o manifesto de uma skill.
### `src/agent/skills/authoring/service.py`

**Propósito:** criar skills a partir de pedidos, propor melhorias e testar skills antes de usá-las.. camada de aplicação — fluxo de autoria, do rascunho à skill aprovada.

- `Proposal` — Uma proposta de melhoria de skill, vinda de uma execução real.
- `Proposal.as_dict() -> dict[str, Any]` — Representação serializável da proposta.
- `SkillAuthoringService` — Fluxo de autoria de skills sobre um repositório de skills.
- `SkillAuthoringService.__init__(store: SkillStore) -> None` — Cria o serviço.
- `SkillAuthoringService.create_draft(name: str, description: str, *, activation: list[str] | None=None, prohibited: list[str] | None=None, tools: list[str] | None=None, procedures: list[str] | None=None, validation: list[str] | None=None, risks: list[str] | None=None, prerequisites: list[str] | None=None, requires_binaries: list[str] | None=None, version: str='1.0.0') -> dict[str, Any]` — Cria uma skill em estado de rascunho.
- `SkillAuthoringService.validate(name: str) -> dict[str, Any]` — Valida uma skill e avança o estado quando ela passa.
- `SkillAuthoringService.test(name: str, *, timeout: float=120.0) -> dict[str, Any]` — Executa os testes da skill, quando ela tem pasta `tests`.
- `SkillAuthoringService.propose(skill: str, title: str, rationale: str, *, changes: str='', evidence: list[str] | None=None) -> dict[str, Any]` — Registra uma proposta de melhoria vinda de uma execução.
- `SkillAuthoringService.list_proposals(*, skill: str | None=None) -> list[dict[str, Any]]` — Lista as propostas registradas.
- `SkillAuthoringService.resolve_proposal(proposal_id: str, *, accept: bool, note: str='') -> dict[str, Any]` — Aceita ou rejeita uma proposta.
### `src/agent/skills/authoring/store.py`

**Propósito:** instalar, ativar, atualizar, versionar e reverter skills criadas pelo agente.. camada de aplicação — ciclo de vida das skills no disco, com histórico e proveniência.

- `hash_tree(root: str | Path) -> str` — Calcula o resumo do conteúdo de uma pasta.
- `copy_tree(source: str | Path, target: str | Path) -> None` — Copia uma pasta ignorando artefatos de build.
- `declared_name(source: str | Path) -> str` — Nome declarado pela skill na origem, quando existe e é válido.
- `InstalledSkill` — Uma skill instalada no repositório de skills.
- `InstalledSkill.as_dict() -> dict[str, Any]` — Representação serializável da skill instalada.
- `SkillStore` — Repositório de skills do agente, com ciclo de vida e histórico.
- `SkillStore.__init__(root: str | Path) -> None` — Cria o repositório.
- `SkillStore.path_of(name: str) -> Path` — Caminho da pasta de uma skill.
- `SkillStore.read_manifest(name: str) -> dict[str, Any]` — Lê o manifesto de uma skill instalada.
- `SkillStore.list_installed() -> list[InstalledSkill]` — Lista as skills instaladas.
- `SkillStore.get(name: str) -> InstalledSkill | None` — Skill instalada pelo nome.
- `SkillStore.search(query: str, *, limit: int=20) -> list[InstalledSkill]` — Pesquisa skills por nome ou descrição.
- `SkillStore.validate(name: str) -> ValidationResult` — Valida uma skill instalada.
- `SkillStore._write_manifest(name: str, manifest: dict[str, Any]) -> None` — Grava o manifesto de uma skill.
- `SkillStore.install(source: str | Path, *, name: str | None=None, origin: str='import', state: str='draft', force: bool=False) -> dict[str, Any]` — Instala uma skill a partir de uma pasta externa.
- `SkillStore._collect(root: Path, folder: str) -> list[str]` — Lista os arquivos de uma subpasta da skill.
- `SkillStore.set_state(name: str, state: str, *, note: str='') -> dict[str, Any]` — Muda o estado de uma skill no ciclo de vida.
- `SkillStore.activate(name: str) -> dict[str, Any]` — Ativa uma skill validada.
- `SkillStore.deactivate(name: str, *, note: str='') -> dict[str, Any]` — Desativa uma skill, sem apagar o conteúdo.
- `SkillStore.update(name: str, source: str | Path, *, version: str | None=None) -> dict[str, Any]` — Atualiza uma skill instalada a partir de uma nova versão.
- `SkillStore.rollback(name: str, *, version: str | None=None) -> dict[str, Any]` — Restaura uma versão anterior de uma skill.
- `SkillStore.history(name: str) -> dict[str, Any]` — Histórico de alterações de uma skill.
- `SkillStore.remove(name: str, *, confirm: bool=False) -> dict[str, Any]` — Remove uma skill do repositório.
### `src/agent/skills/authoring/validator.py`

**Propósito:** validar a integridade de uma skill autoral antes de ela ser ativada.. camada de aplicação — checagem de nome, metadados, arquivos referenciados e dependências.

- `ValidationResult` — Veredito da validação de uma skill.
- `ValidationResult.as_dict() -> dict[str, Any]` — Representação serializável do veredito.
- `validate_name(name: str) -> str | None` — Valida o nome de uma skill.
- `validate_skill(root: str | Path) -> ValidationResult` — Valida uma pasta de skill.
- `_referenced_files(text: str, manifest: dict[str, Any]) -> list[str]` — Coleta os arquivos referenciados no `SKILL.md` e no manifesto.
- `_listed_files(layout: SkillLayout, manifest: dict[str, Any]) -> list[str]` — Coleta os arquivos declarados no manifesto.
- `dependency_report(manifest: dict[str, Any]) -> dict[str, Any]` — Relata as dependências de uma skill e o que está ausente.
### `src/agent/system/__init__.py`

**Propósito:** expor a camada de automação do sistema (processos, aplicativos, diagnóstico).. camada de infraestrutura — ponto de entrada estável para o resto do agente.

### `src/agent/system/README.md`

**Propósito:** Índice dos adaptadores de sistema: processos, aplicativos e diagnóstico por plataforma.
### `src/agent/system/adapters.py`

**Propósito:** isolar as diferenças de sistema operacional na automação do sistema.. camada de infraestrutura — comandos nativos por plataforma e detecção do SO.

- `current_os() -> str` — Sistema operacional canônico do ambiente atual.
- `SystemAdapter` — Comandos e capacidades de automação de uma plataforma.
- `SystemAdapter.supports(binary: str) -> bool` — Indica se um executável usado por este adaptador está disponível.
- `SystemAdapter.missing_tools() -> list[str]` — Executáveis necessários e ausentes.
- `MacAdapter(SystemAdapter)` — Adaptador de macOS: `ps`, `open`, `osascript` e `screencapture`.
- `WindowsAdapter(SystemAdapter)` — Adaptador de Windows: PowerShell para processos e janelas, UIAutomation opcional.
- `LinuxAdapter(SystemAdapter)` — Adaptador de Linux: `ps`, `xdg-open` e ferramentas de sessão (X11/Wayland).
- `get_adapter(os_name: str | None=None) -> SystemAdapter` — Adaptador da plataforma.
- `session_kind() -> str` — Natureza da sessão gráfica do ambiente atual.
### `src/agent/system/apps.py`

**Propósito:** descobrir aplicativos instalados e abrir aplicativos, arquivos, pastas e URLs.. camada de infraestrutura — catálogo de aplicativos e abertura de recursos do sistema.

- `AppInfo` — Um aplicativo discovered no sistema.
- `AppInfo.as_dict() -> dict[str, Any]` — Representação serializável do aplicativo.
- `_macos_apps() -> list[AppInfo]` — Descobre aplicativos do macOS lendo o `Info.plist` de cada bundle.
- `_linux_apps() -> list[AppInfo]` — Descobre aplicativos do Linux pelos arquivos `.desktop`.
- `_windows_apps() -> list[AppInfo]` — Descobre aplicativos do Windows pelos atalhos do menu Iniciar.
- `list_apps(match: str | None=None, limit: int=100) -> list[AppInfo]` — Descobre os aplicativos instalados no sistema.
- `find_app(name: str) -> AppInfo | None` — Procura um aplicativo pelo nome, exato ou parcial.
- `_resolve_executable(name: str) -> str | None` — Localiza o executável de um aplicativo pelo `PATH`.
- `launch_app(name: str, *, args: Sequence[str] | None=None, cwd: str | None=None, env: dict[str, str] | None=None, background: bool=False, manager: ProcessManager | None=None) -> dict[str, Any]` — Abre um aplicativo pelo nome, caminho ou executável disponível.
- `open_path(path: str, *, manager: ProcessManager | None=None) -> dict[str, Any]` — Abre um arquivo, pasta ou URL com o manipulador padrão do sistema.
### `src/agent/system/platform_info.py`

**Propósito:** descrever o ambiente de execução e diagnosticar bloqueios do sistema operacional.. camada de infraestrutura — sistema, sessão gráfica, permissões e limitações.

- `describe_system() -> dict[str, Any]` — Descreve o computador onde o agente roda.
- `_macos_permissions() -> list[dict[str, Any]]` — Verifica as permissões do TCC no macOS.
- `_windows_permissions() -> list[dict[str, Any]]` — Verifica as condições de sessão e privilégio no Windows.
- `_linux_permissions() -> list[dict[str, Any]]` — Verifica as condições de sessão no Linux.
- `diagnose_permissions() -> dict[str, Any]` — Diagnostica as permissões que a automação de interface pode exigir.
- `platform_summary() -> str` — Resumo textual do ambiente, para o agente decidir o modo de automação.
### `src/agent/system/processes.py`

**Propósito:** listar, inspecionar, encerrar e acompanhar processos autorizados do sistema.. camada de infraestrutura — inventário de processos e tarefas longas em segundo plano.

- `ProcessInfo` — Um processo do sistema, visto pelo agente.
- `ProcessInfo.as_dict() -> dict[str, Any]` — Representação serializável do processo.
- `_parse_elapsed(raw: str) -> int | None` — Converte a idade de processo do `ps` para segundos.
- `_parse_ps_output(text: str) -> list[ProcessInfo]` — Interpreta a saída do comando de listagem de processos.
- `list_processes(match: str | None=None, limit: int=50) -> list[ProcessInfo]` — Lista os processos do sistema.
- `process_info(pid: int) -> ProcessInfo | None` — Inspeciona um processo pelo identificador.
- `terminate_process(pid: int, *, force: bool=False, timeout: float=5.0) -> dict[str, Any]` — Encerra um processo autorizado.
- `ProcessHandle` — Tarefa longa em segundo plano, com saída parcial e cancelamento.
- `ProcessHandle.as_dict() -> dict[str, Any]` — Representação serializável da tarefa.
- `ProcessManager` — Rastreia tarefas longas em segundo plano.
- `ProcessManager.__init__(log_dir: str | None=None) -> None` — Cria o gerenciador.
- `ProcessManager.start(command: Sequence[str], *, cwd: str | None=None, env: dict[str, str] | None=None) -> ProcessHandle` — Inicia um processo em segundo plano e devolve o identificador da tarefa.
- `ProcessManager.get(handle_id: str) -> ProcessHandle | None` — Tarefa pelo identificador, com o estado atualizado.
- `ProcessManager.list() -> list[ProcessHandle]` — Todas as tarefas rastreadas, com o estado atualizado.
- `ProcessManager.output(handle_id: str, *, tail_bytes: int=8000) -> dict[str, Any]` — Saída parcial de uma tarefa em segundo plano.
- `ProcessManager.cancel(handle_id: str, *, force: bool=False) -> dict[str, Any]` — Cancela uma tarefa em segundo plano.
- `ProcessManager.reap() -> int` — Fecha os descritores e remove as tarefas já terminadas.
- `_tail(path: str, limit: int) -> str` — Lê a cauda de um arquivo de log.
- `format_command(command: Sequence[str]) -> str` — Formata um comando para exibição.
