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
10. **Skills** — ativação lexical por palavra-chave; pedido muito indireto pode não ativar a skill ideal. O catálogo é relido do disco a cada `reload()`.
11. **Estratégia** — classifica por domínios fixos (consulta, QA, bug, refatoração, documentação, engenharia); pedidos híbridos ficam no domínio mais próximo.
12. **Recuperação da verificação** — reexecuta o mesmo verificador; não há estratégia de verificação alternativa nem leitura semântica da causa.
13. **Provedores** — a compatibilidade com OpenAI cobre `chat/completions`, `models`, streaming SSE, `tools` e `response_format`; não há `embeddings`, `audio` nem API em lote. As chamadas de ferramenta chegam na resposta (`tool_calls`), mas o ciclo de ferramentas do agente continua sendo o atual (JSON de operação). Anthropic não tem JSON estruturado nativo. Detalhes: [provedores.md](/docs/architecture/provedores.md).

Detalhes: [skills-estrategia.md](/docs/architecture/skills-estrategia.md).

Testes: `pytest` (41+ casos) · E2E mock: `tests/test_e2e_orchestrator.py` · recuperação: `tests/test_orchestrator_recovery.py`.

Backup: [scripts/backup-data.sh](/scripts/backup-data.sh).

Voltar: [architecture/README.md](/docs/architecture/README.md)

14. **Diagnóstico de provedor** — `GET /providers/{nome}/health` e `POST /providers/{nome}/test`
    respondem sempre com `ok: true/false` e o motivo; nunca estouram erro 500. A lista de modelos
    (`GET /providers/{nome}/models`) devolve 503 quando o servidor não responde.
15. **Remoção em cascata** — a remoção de projeto e de conversa segue o grafo de chaves estrangeiras
    do modelo (`src/agent/services/cascade.py`); se alguma linha pendurada escapar, a API responde
    409 com o motivo em vez de 500.
