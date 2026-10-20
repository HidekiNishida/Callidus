# Testes (`tests/`)

![testes](/media/icons/testes.svg){width=48}

Como a suíte é organizada e o que cada arquivo verifica.

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
| [test_automation_runtime.py](/tests/test_automation_runtime.py) | **Automações** — máquina de estados do disparo, cron/intervalo/once, eventos internos, idempotência, recuperação, dependências, segurança, migração |
| [test_automation_platforms.py](/tests/test_automation_platforms.py) | Adaptadores nativos — `launchd`, `systemd`, Agendador de Tarefas do Windows (unidade e simulação) |
| [test_automation_api.py](/tests/test_automation_api.py) | HTTP das automações — criar, ativar, suspender, executar, testar, cancelar, remover, status do supervisor |
| [test_automation_end_to_end.py](/tests/test_automation_end_to_end.py) | Fluxo de aceitação — sobrevive ao encerramento do processo, dispara, executa, persiste evidência |

Fixtures: [fixtures/README.md](/tests/fixtures/README.md)

Voltar: [README](/README.md)