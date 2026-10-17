# Checklist: núcleo do agente (Fase 0–1)

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-10-17 |
| Atualizado em | 2026-10-17 |
| Agente / tarefa | Construção agente local — prompt principal |
| Regras consultadas | [Hub](/docs/regras/README.md) |

## Objetivo

Estabelecer arquitetura documentada e núcleo persistente (projetos, árvore de tarefas, máquina de estados, eventos, API) com testes automatizados.

## Próxima ação

Fase 2: orquestrador + persistência de tentativas de modelo; Fase 3: ferramentas de arquivo/shell.

## Etapas

- [x] Diagnóstico do repositório (só docs → código novo em `src/agent/`)
- [x] Documentação de arquitetura em `docs/architecture/`
- [x] Modelo SQLite + serviços + transições
- [x] API FastAPI inicial
- [x] Provedores Ollama / llama.cpp (HTTP)
- [x] Orçamento de contexto (heurística)
- [x] Testes unitários e API
- [ ] Orquestrador completo (decomposição, ferramentas, verificação)
- [ ] Interface web (Vite + React)
- [ ] Cenário E2E reproduzível
- [ ] Verificação final ([verificacao-final.md](/docs/regras/verificacao-final.md))
- [ ] Commit em português ([commits.md](/docs/regras/commits.md))

## Bloqueios

- Nenhum para Fase 0–1.

## Artefatos

| Path | Notas |
|------|-------|
| `/docs/architecture/` | Visão, dados, estados, execução local |
| `/src/agent/` | Código Python |
| `/tests/` | pytest |

## Notas de retomada

Stack: Python 3.11+, FastAPI, SQLAlchemy, SQLite em `data/`. Rodar `pip install -e ".[dev]"` e `pytest`. API: `agente-api` na porta 8765.
