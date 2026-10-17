# Orquestrador (`agent.orchestrator`)

Lógica **determinística** do ciclo: decompor → executar → verificar → consolidar.

| Módulo | Função |
|--------|--------|
| [runner.py](/src/agent/orchestrator/runner.py) | `RunOrchestrator`, passos |
| [decomposition.py](/src/agent/orchestrator/decomposition.py) | Plano (Ollama padrão) |
| [consolidation.py](/src/agent/orchestrator/consolidation.py) | Bottom-up |
| [engine.py](/src/agent/orchestrator/engine.py) | Legado mínimo |

Ordem de decomposição: builtin e2e → **Ollama** → template genérico → mock (se permitido).

Voltar: [agent/README.md](/src/agent/README.md)
