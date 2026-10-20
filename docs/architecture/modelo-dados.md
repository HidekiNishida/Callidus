# Modelo de dados

O modelo de dados: as 22 tabelas, seus campos e as transições gravadas.

Persistência principal: SQLite em `data/agent.db` (configurável via `AGENT_DATA_DIR`).

## 🏗️ Entidades

| Entidade | Responsabilidade |
|----------|------------------|
| `Project` | Workspace lógico: nome, path raiz autorizado, config |
| `ProjectRemote` | Computador remoto do projeto: host, porta, usuário, chave, pasta (segredo nunca exposto) |
| `Conversation` | Conversa: título, idioma, escopo; é a raiz do trabalho quando a tarefa pertence a ela |
| `Branch` | Ramo de uma conversa: fork com contexto próprio |
| `Task` | Nó da árvore: objetivo, escopo, estado, pai, ordem |
| `TaskDependency` | Aresta dirigida: `depends_on_task_id` deve concluir antes |
| `ExecutionRun` | Uma “sessão” de orquestração sobre um objetivo |
| `ScheduledRun` | Disparo agendado herdado do protótipo anterior (convivem com `automations`) |
| `Automation` | Definição versionada de uma automação: gatilho, ação, dependências, permissões |
| `AutomationFiring` | Registro de um disparo, com chave de idempotência por instante elegível |
| `AutomationEvent` | Trilha durável dos eventos do runtime de automações |
| `OperationAttempt` | Tentativa de operação (modelo ou ferramenta) |
| `EventLog` | Trilha append-only para auditoria e retomada |
| `MemoryRecord` | Memória tipada (canônica, execução, contexto, evidência, procedimento) |
| `Evidence` | Resultado de verificação ou ferramenta, ligado à tarefa |
| `KgNode` / `KgEdge` | Grafo de conhecimento (arquivo, símbolo, documento, requisito) |
| `TaskContract` | Entradas/saídas/invariantes de integração por tarefa |
| `ContextSnapshot` | Métricas e componentes do contexto enviado ao modelo |
| `Agent` | Agente lógico: papel, instruções, permissões, pai e estado |
| `AgentExecution` | Execução ativa do agente: checkpoint, tentativa, erro |
| `AgentQuery` | Consulta entre agentes: perguntas, correlação, tentativas, resposta |

São 22 tabelas. `projects`, `tasks`, `execution_runs`, `operation_attempts` e `event_logs` são
o núcleo do ciclo; as demais descrevem conversas, agentes, memórias, evidências e automações.

## 🏗️ Task — campos essenciais

- `id` (UUID), `project_id`, `parent_id` (nullable = raiz do objetivo)
- `title`, `objective`, `scope`, `acceptance_criteria` (JSON/texto)
- `status` — enum [`TaskStatus`](/docs/architecture/maquina-estados.md)
- `kind` — `objective` | `subsystem` | `operation` (extensível)
- `metadata_json` — entradas/saídas esperadas, limites, ferramentas autorizadas
- `consolidated_result_json` — resumo após conclusão verificada
- timestamps: `created_at`, `updated_at`, `started_at`, `completed_at`

## 🏗️ Hierarquia de agentes

Três entidades distintas, com ciclo de vida próprio:

| Tabela | Chave | Papel |
|--------|-------|-------|
| `agents` | `id`, `project_id`, `parent_id` (agente pai), `task_id`, `role`, `status`, `depth`, `metadata_json` | Identidade, papel, hierarquia recursiva e descobertas |
| `agent_executions` | `id`, `agent_id`, `task_id`, `run_id`, `status`, `attempt`, `checkpoint_json`, `context_refs_json`, `last_error` | O que ocupa memória de inferência e como retomá-lo |
| `agent_queries` | `id`, `requester_agent_id`, `target_agent_id`, `answered_by_agent_id`, `task_id`, `correlation_id`, `questions_json`, `status`, `answer_json`, `attempts` | Pergunta entre agentes e resposta correlacionada |

- `agents.parent_id` é auto-referente: a profundidade não é fixa.
- `agent_executions.checkpoint_json` guarda o estado **estruturado** (etapa, plano,
  pendências, erros), limitado por `MAX_AGENT_CHECKPOINT_CHARS`. A transcrição bruta
  continua em `event_logs`, que é a trilha de auditoria.
- `metadata_json` do agente guarda as descobertas (`findings`), as decisões e os
  artefatos — é o que permite responder a uma consulta sem reexecutar o trabalho.

Detalhe: [hierarquia-agentes.md](/docs/architecture/hierarquia-agentes.md).

## 🧠 Memória

Tipos (`MemoryKind`):

- `canonical` — requisitos/decisões que não podem ser apagados por resumo
- `execution` — plano, tentativas, bloqueios
- `contextual` — referências a arquivos/trechos
- `evidence` — testes, logs, comandos
- `procedure` — padrões reutilizáveis com escopo

Compactação futura: nova versão com `source_refs` apontando para registros anteriores.

## 🔄 Eventos

Cada transição relevante grava `EventLog`: `run_id`, `task_id`, `type`, `payload_json`, `created_at`, `seq` (monotônico por run), `parent_task_id`, `agent` e `schema_version`. Catálogo, contexto e entrega em tempo real: [execucao-autonoma.md](execucao-autonoma.md).

Tarefas: `task.created` e uma mudança de status por evento tipado (`task.started`, `task.progress`, `task.blocked`, `task.completed`, `task.failed`, `task.cancelled`, todos com `from`/`to`/`reason`; bancos antigos têm `task.status_changed`). Run: `run.started`, `run.progress`, `run.completed`, `run.failed` (`kind: stalled` quando nada pode avançar), `run.cancelled`, `run.paused`, `run.resumed`; `attempt.recorded`. Controle de progresso: `run.stagnation` (diagnóstico da etapa que repete o erro), `run.paused` (com limite, pendências e próxima ação) e `run.resumed` (o orçamento dos limites recomeça daqui).