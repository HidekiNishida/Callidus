# CALLIDUS — descobertas e decisões

## Confirmado

1. **Narração no topo:** causada por `splitFeed` + lista HTML separada (corrigido).
2. **Feed vazio ao reabrir conversa:** `selectConversation` zera `state.feeds` e nada repopulava `/observe` (corrigido com `hydrateFeedsFromHistory`).
3. **Ollama `gpt-oss:20b`:** integração funcional via `meu_ollama` + `model_id` na run (~2,6 min para tarefa simples com ferramentas).
4. **Testes:** 44 testes Node web; 892 pytest (suite completa, ambiente local).

## Provável

- Narração após a operação (sem evento intermediário) cai na **última** linha operacional (`integrateNarrative`) — aceitável até haver `correlation_id` no backend.
- Duplicata visual entre `agent.thought` (lista `.thoughts`) e `work.explained` no feed — backend emite ambos em alguns caminhos.

## Desconhecido / não testado

- Comportamento com múltiplas runs na mesma mensagem raiz (só a run mais recente hidrata).
- OpenRouter como default enquanto auditoria pede Ollama — requer troca manual na UI ou `model_id` na run.

## Decisões

- Manter `splitFeed` apenas para classificação em testes.
- Fixture `tests/web/fixtures/observe-with-narration.json` ancorada em run real (reprodutível offline).
- Script `scripts/audit_ollama_smoke.sh` para repetir cenário A sem alterar YAML.
