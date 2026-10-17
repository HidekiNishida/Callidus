# Limitações conhecidas (v0.5)

1. **Decomposição LLM** — depende de Ollama reachable; fallback template genérico pode ser grosso em repos grandes.
2. **Visão** — referências preparadas; envio multimodal ao provedor requer perfil `supports_vision`.
3. **Concorrência** — uma operação por vez no orquestrador.
4. **Streaming de tokens** — não exposto na UI.
5. **MCP** — servidores pesados (npm) podem falhar por timeout; ajuste comando/cwd.
6. **Aprovações** — flag `approve_risky_tools` no run; UI granular pendente.
7. **Grafo** — indexação Python-first; relações `imports`/`calls` ainda heurísticas.
8. **Atomização** — micro-plano determinístico; decomposição LLM profunda ainda limitada.
9. **Contratos** — validação manual via `requires_contract`; propagação de impacto incompleta.

Testes: `pytest` (30+ casos) · E2E mock: `tests/test_e2e_orchestrator.py`.

Backup: [scripts/backup-data.sh](/scripts/backup-data.sh).

Voltar: [architecture/README.md](/docs/architecture/README.md)
