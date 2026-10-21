# CALLIDUS — checkpoint (conclusão da auditoria)

Atualizado: 2026-10-21

## Entregue

- P1 narração: `integrateNarrative`, UI inline, testes `work-explained` + `narrative-replay`.
- P1 histórico: `hydrateFeedsFromHistory` / `replayFeedFromRun` em `store.js`.
- E2E Ollama cenário A: run `7e2b2c40-ded5-4880-b29a-8adaf20afd30` (log em `.cursor/e2e-ollama-smoke.log`).
- Documentação: `.cursor/CALLIDUS_*.md`.

## Testes

- `node --test tests/web/*.test.mjs` → 44 pass
- `python -m pytest tests/ -q` → 892 pass

## Git

Alterações locais **sem commit** (salvo pedido explícito).

## Arquivos principais

`ui.js`, `chat.js`, `style.css`, `store.js`, `tests/web/narrative-replay.test.mjs`, `tests/web/fixtures/observe-with-narration.json`, `scripts/audit_ollama_smoke.sh`, `resume.md`.
