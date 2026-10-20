# Checklist: agente local — fases 0–8

![tarefas](/media/icons/tarefas.svg){width=48}

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-17 |
| Atualizado em | 2026-10-17 |
| Agente / tarefa | Construção completa solicitada |
| Regras consultadas | [Hub](/docs/regras/README.md) |

## 🎯 Objetivo

Entregar runtime funcional com API, orquestrador, ferramentas, verificação, UI web, testes E2E e documentação.

## 🔄 Etapas

- [x] Fases 0–1 (núcleo persistente)
- [x] Fases 2–5 (runtime, ferramentas, decomposição, verificação)
- [x] Fase 6 (UI `web/static/`)
- [x] Fase 7 parcial (MCP config + visão preparada)
- [x] Fase 8 (pytest 19 testes, E2E mock)
- [x] Script backup `scripts/backup-data.sh`
- [x] Documentação `docs/architecture/*`
- [x] Commits em português

## Artefatos

| Path | Notas |
|------|-------|
| `/src/agent/` | Código completo |
| `/web/static/` | Interface |
| `/tests/test_e2e_orchestrator.py` | E2E |
| `/docs/architecture/limitacoes.md` | Pendências honestas |

## Notas de retomada

MCP stdio e decomposição LLM genérica são os principais gaps. Ollama real: `GET /providers/ollama/models` + config `provider: ollama` no run.