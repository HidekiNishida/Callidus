# Domínio (`agent.domain`)

Contratos e regras de negócio **sem I/O**.

| Arquivo | Conteúdo |
|---------|----------|
| [enums.py](/src/agent/domain/enums.py) | Status, tipos de memória |
| [schemas.py](/src/agent/domain/schemas.py) | Pydantic (API) |
| [state_machine.py](/src/agent/domain/state_machine.py) | Transições de tarefa |
| [failures.py](/src/agent/domain/failures.py) | Taxonomia de falhas (categoria + causa) e classificadores puros |

Doc: [maquina-estados.md](/docs/architecture/maquina-estados.md)

Voltar: [agent/README.md](/src/agent/README.md)
