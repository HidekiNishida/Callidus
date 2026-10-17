# Modelo de dados

Persistência principal: SQLite em `data/agent.db` (configurável via `AGENT_DATA_DIR`).

## Entidades

| Entidade | Responsabilidade |
|----------|------------------|
| `Project` | Workspace lógico: nome, path raiz autorizado, config |
| `Task` | Nó da árvore: objetivo, escopo, estado, pai, ordem |
| `TaskDependency` | Aresta dirigida: `depends_on_task_id` deve concluir antes |
| `ExecutionRun` | Uma “sessão” de orquestração sobre um objetivo |
| `OperationAttempt` | Tentativa de operação (modelo ou ferramenta) |
| `EventLog` | Trilha append-only para auditoria e retomada |
| `MemoryRecord` | Memória tipada (canônica, execução, contexto, evidência, procedimento) |
| `Evidence` | Resultado de verificação ou ferramenta, ligado à tarefa |

## Task — campos essenciais

- `id` (UUID), `project_id`, `parent_id` (nullable = raiz do objetivo)
- `title`, `objective`, `scope`, `acceptance_criteria` (JSON/texto)
- `status` — enum [`TaskStatus`](/docs/architecture/maquina-estados.md)
- `kind` — `objective` | `subsystem` | `operation` (extensível)
- `metadata_json` — entradas/saídas esperadas, limites, ferramentas autorizadas
- `consolidated_result_json` — resumo após conclusão verificada
- timestamps: `created_at`, `updated_at`, `started_at`, `completed_at`

## Memória

Tipos (`MemoryKind`):

- `canonical` — requisitos/decisões que não podem ser apagados por resumo
- `execution` — plano, tentativas, bloqueios
- `contextual` — referências a arquivos/trechos
- `evidence` — testes, logs, comandos
- `procedure` — padrões reutilizáveis com escopo

Compactação futura: nova versão com `source_refs` apontando para registros anteriores.

## Eventos

Cada transição relevante grava `EventLog`: `run_id`, `task_id`, `type`, `payload_json`, `created_at`.

Tipos iniciais: `task.created`, `task.status_changed`, `run.started`, `run.paused`, `attempt.recorded`.
