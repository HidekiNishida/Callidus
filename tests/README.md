# Testes (`tests/`)

Suíte **pytest** — `pytest` na raiz do repo (config em [pyproject.toml](/pyproject.toml)).

| Arquivo | Escopo |
|---------|--------|
| [test_state_machine.py](/tests/test_state_machine.py) | Transições |
| [test_persistence.py](/tests/test_persistence.py) | SQLite |
| [test_api.py](/tests/test_api.py) | HTTP |
| [test_tools.py](/tests/test_tools.py) | Ferramentas |
| [test_e2e_orchestrator.py](/tests/test_e2e_orchestrator.py) | Fluxo e2e mock |
| [test_mcp_manager.py](/tests/test_mcp_manager.py) | MCP config |
| [test_decomposition.py](/tests/test_decomposition.py) | Planos |
| [test_inference_executor.py](/tests/test_inference_executor.py) | Executor compartilhado — exclusividade, espera, cancelamento |
| [test_agent_service.py](/tests/test_agent_service.py) | Agente lógico — ciclo de vida, checkpoint, descarte |
| [test_query_service.py](/tests/test_query_service.py) | Consultas entre agentes — correlação, ciclos, estado persistido |
| [test_agent_scheduler.py](/tests/test_agent_scheduler.py) | Escalonador — ordem, duplicidade, erro, tempo limite |
| [test_agent_hierarchy_e2e.py](/tests/test_agent_hierarchy_e2e.py) | Hierarquia de 3+ gerações — ponta a ponta, reinício, retomada |
| [test_agent_api.py](/tests/test_agent_api.py) | HTTP da hierarquia de agentes |

Fixtures: [fixtures/README.md](/tests/fixtures/README.md)

Voltar: [README](/README.md)
