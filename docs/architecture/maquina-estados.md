# Máquina de estados das tarefas

Estados (`TaskStatus`):

| Estado | Significado |
|--------|-------------|
| `PENDING` | Criada, ainda não planejada |
| `PLANNING` | Decomposição/planejamento em curso |
| `READY` | Dependências satisfeitas, pronta para executar |
| `RUNNING` | Operação em andamento |
| `VERIFYING` | Verificações pós-operação |
| `RETRY_PENDING` | Falha recuperável; aguarda nova tentativa |
| `BLOCKED` | Impedimento real documentado |
| `COMPLETED` | Critérios satisfeitos com evidência |
| `FAILED` | Falha não recuperável dentro dos limites |
| `CANCELLED` | Interrompida pelo usuário |

## Transições permitidas (implementação: `domain/state_machine.py`)

```mermaid
stateDiagram-v2
  [*] --> PENDING
  PENDING --> PLANNING
  PLANNING --> READY
  PLANNING --> BLOCKED
  READY --> RUNNING
  RUNNING --> VERIFYING
  RUNNING --> RETRY_PENDING
  RUNNING --> FAILED
  VERIFYING --> COMPLETED
  VERIFYING --> RETRY_PENDING
  VERIFYING --> RUNNING
  RETRY_PENDING --> READY
  RETRY_PENDING --> BLOCKED
  PENDING --> CANCELLED
  PLANNING --> CANCELLED
  READY --> CANCELLED
  RUNNING --> CANCELLED
  RETRY_PENDING --> CANCELLED
  BLOCKED --> PLANNING
  BLOCKED --> CANCELLED
```

Transições inválidas levantam `InvalidTransitionError` — nunca silenciosamente.

## Conclusão

`COMPLETED` exige passagem por `VERIFYING` (exceto tarefas marcadas como `no_verification` no metadata, uso restrito a testes).

O orquestrador (fases posteriores) não promove para `COMPLETED` só porque subtarefas retornaram texto.
