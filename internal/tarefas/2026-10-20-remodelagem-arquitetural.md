# Checklist: Remodelagem arquitetural, documentação e manutenibilidade

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-10-20 |
| Atualizado em | 2026-10-20 |
| Agente / tarefa | Remodelagem arquitetural completa (orquestrador, API, documentação, regras) |
| Regras consultadas | [Hub](/docs/regras/README.md) · [AGENTS.md](/AGENTS.md) |

## Objetivo

Deixar o Callidus mais fácil de compreender e de modificar sem perder identidade nem contrato:
separar o **ciclo** do run da **execução** de uma tarefa, organizar a API em roteadores por
assunto, padronizar cabeçalho e docstrings de todo o código e deixar a documentação indexada.

## Próxima ação

Aguardar o fim da padronização de cabeçalhos/docstrings em `src/`; depois, auditoria final
(links, imports, drift, suíte) e commits em português.

## Etapas

- [x] Etapa A — diagnóstico: inventário, baseline (661 testes), problemas confirmados
- [x] Etapa B — convenções: `AGENTS.md` como fonte canônica; padrão de cabeçalho de 7 campos
- [x] Etapa C1 — `orchestrator/execution/`: execução de uma tarefa fora do `runner.py`
- [x] Etapa C2 — `api/` como fachada de roteadores por assunto
- [x] Etapa C3 — remover código inalcançável e regras de escrita duplicadas
- [x] Etapa D — padronizar cabeçalhos e docstrings (src, tests, scripts, web)
- [x] Etapa E — testes: novo `tests/test_execution_package.py` (14 casos) e suíte completa
- [ ] Etapa F — auditoria final: links, imports, drift de código, suíte, smoke da API
- [ ] Commits em português, sem as alterações preexistentes do usuário

## Bloqueios

- `python scripts/resume.py check` reprova desde antes desta tarefa (~999 itens sem
  descrição no `resume.md` — pastas, `.md`, `media/`, `lab/`). Como `carimbar` só grava
  quando nada falta, o carimbo do inventário está congelado. **Não resolvido aqui**: é uma
  lacuna pré-existente do inventário, não da refatoração. Documentado no relatório final.
- `tests/test_web_frontend.py` continua com o cabeçalho antigo: é arquivo em edição pelo
  usuário e não foi tocado.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/AGENTS.md` | Regras de engenharia (fonte canônica) |
| `/docs/README.md` | Índice geral de nível 1 |
| `/docs/architecture/decisoes-arquitetura.md` | ADR-001 a ADR-005 |
| `/src/agent/orchestrator/execution/README.md` | Contrato do pacote de execução |
| `/src/agent/api/README.md` | Mapa dos roteadores |
| `/scripts/check_imports.py` | Confere importações/definições preservadas |
| `/scripts/check_code_drift.py` | Detecta mudança de código disfarçada de docstring |
| `/scripts/check_docs.py` | Confere links internos da documentação |
| `/scripts/padronizar_cabecalhos.py` | Aplica o cabeçalho padrão sem tocar no código |
| `/tests/test_execution_package.py` | Testes do pacote de execução |

## Notas de retomada

O `runner.py` passou de ~2150 para ~1000 linhas: a execução de uma tarefa mora em
`src/agent/orchestrator/execution/`. O provedor continua injetável por
`runner._select_provider` (mesmo ponto de injeção usado pelos testes). A API foi dividida em
`system_/project_/conversation_/task_/run_routes.py` + `presenters.py` + `live_view.py`;
`main.py` é a fachada. Nenhum endpoint, status, payload, evento ou estado mudou.
