# Limitações conhecidas (v0.2)

1. **MCP** — configuração only; conexão stdio não implementada.
2. **Visão** — módulo de referências (`vision/context.py`); envio multimodal ao provedor depende de perfil com `supports_vision`.
3. **Decomposição LLM** — fallback builtin para objetivos `e2e`/`calc`; outros objetivos exigem modelo local funcional ou plano manual via API.
4. **Concorrência** — uma operação por vez no orquestrador.
5. **Streaming** — inferência sem SSE de tokens (apenas eventos de tarefa).
6. **Aprovações** — flag global `approve_risky_tools` no config do run; UI de aprovação granular pendente.

Testes: `pytest` (19 casos) incluindo E2E mock em `tests/test_e2e_orchestrator.py`.

Backup: `./scripts/backup-data.sh` antes de upgrades de schema.
