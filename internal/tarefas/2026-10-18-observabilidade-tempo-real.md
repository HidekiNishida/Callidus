# Checklist: Observabilidade em tempo real

| Campo | Valor |
|-------|-------|
| Estado | em andamento |
| Criado em | 2026-10-18 |
| Atualizado em | 2026-10-18 |
| Agente / tarefa | Eventos unificados, streaming dos provedores, SSE com recuperação, interface de acompanhamento |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md) |
| Antecessor | [validação, verificação e progresso](/internal/tarefas/2026-10-18-validacao-verificacao-progresso.md) (concluída) |

## Objetivo

Tornar a execução observável em tempo real a partir do executor real: eventos tipados e persistidos, respostas do modelo em fragmentos quando o provedor transmite, ferramentas, comandos, arquivos e verificações com dados reais, transmissão com reconexão e recuperação, e uma interface de acompanhamento integrada à existente.

## Próxima ação

Unidade 1: contrato de eventos, barramento, emissor e migração.

## Diagnóstico (auditoria)

| # | Achado | Onde |
|---|--------|------|
| O1 | Uma tabela de eventos (`event_logs`: projeto, run, tarefa, tipo, payload, data), sem sequência, tarefa pai, agente nem versão | `persistence/models.py` |
| O2 | Eventos gravados direto (`EventLogModel(...)`) em vários pontos: `orchestrator.action`, `agent.thought`, `attempt.recorded`, `plan.validated`, `run.*`, `task.created`, `task.status_changed` (sem `run_id`) | `runner.py`, `task_service.py`, `attempt_service.py`, `run_service.py` |
| O3 | Interface consulta a cada 2,5 s (`refreshAll`, `/projects/{id}/live`, `/projects/{id}/events` com 200 últimos); nenhum SSE ou WebSocket | `web/static/assets/app.js`, `api/main.py` |
| O4 | Streaming: só Ollama tem `chat_stream` (sem uso de tokens); llama.cpp não; o executor só transmite se `stream` estiver ligado e grava cada fragmento como `agent.thought` com commit | `providers/*.py`, `runner.py` |
| O5 | Três chamadas ao modelo: operação do modelo (`runner`), resposta final (`runner`), decomposição (`decomposition.plan_with_model`) | — |
| O6 | Ferramentas passam por `ToolRegistry.execute`; `ToolContext` já tem `run_id`/`task_id`; escrita e edição devolvem diff real; `_run_command` usa `communicate()` (sem saída progressiva) | `tools/registry.py`, `tools/builtins.py` |
| O7 | Verificação cria o próprio `ToolContext` sem run/tarefa | `verification/runner.py` |
| O8 | Sem autenticação: API local em 127.0.0.1; não há regra de autorização a reaproveitar | `api/main.py`, `config.py` |
| O9 | Migração leve por `_add_column` no SQLite | `persistence/database.py` |
| O10 | Node 24 disponível; frontend sem build nem dependências (ES modules) | `web/static` |

## Decisões

| Tema | Decisão | Por quê |
|------|---------|---------|
| Fonte de verdade | `event_logs` + colunas `seq`, `parent_task_id`, `agent`, `schema_version` | sem banco nem mensageria nova; tarefas continuam em `tasks` |
| Sequência | contador por run no processo, iniciado do maior `seq` gravado; atribuído no `before_flush` a toda linha de evento com run | cobre os produtores antigos sem reescrevê-los |
| Publicação | persistidos: depois do commit (nunca publica o que foi desfeito); fragmentos (`*.delta`, `*.output`, `agent.status`): só memória, com o mesmo contador | fato real primeiro; volume alto fora do banco |
| Contexto | `ContextVar` com sessão, run, tarefa e agente, ligado pelo orquestrador a cada passo | ferramentas, verificação e modelo emitem sem mudar assinaturas |
| Transporte | SSE (`GET /runs/{id}/stream`): unidirecional; `id:` só em eventos persistidos, então `Last-Event-ID` aponta para o banco | reconexão nativa do `EventSource` sem perder o que foi gravado |
| Recuperação | histórico paginado do banco + anel em memória para fragmentos + foto do estado (`/runs/{id}/observe`) com saídas em andamento | reconectar e reabrir sem depender da conexão |
| Interface | `observe-core.js` (estado puro), `observe-view.js` (HTML puro), `observe.js` (DOM/SSE); testes com `node --test` | sem dependência nova; lógica testável |

## Plano

| Unidade | Mudança | Aceite |
|---------|---------|--------|
| 1 | Contrato tipado, sanitização, barramento, emissor, listeners, migração | testes de validação, sequência, sanitização, publicação só após commit |
| 2 | Eventos no executor: run, plano, tarefas, ferramentas, comandos (saída progressiva), arquivos, testes, verificação | eventos com tarefa/pai corretos e só após o fato |
| 3 | Streaming: Ollama e llama.cpp em fragmentos, agrupamento, final sem duplicação, erros; provedor sem streaming mostra estado real | testes com provedor que transmite e que falha no meio |
| 4 | API: histórico paginado e filtrado, SSE com reconexão e fim, foto do estado com tarefas interrompidas | testes de reconexão, deduplicação, runs simultâneos |
| 5 | Interface: cabeçalho, árvore, atividade, respostas, terminal, arquivos, verificação; filtros; reconexão | testes `node --test` |
| 6 | Integração ponta a ponta (executor real → eventos → estado da interface), documentação, validação final | teste realista com falha e recuperação |

## Riscos

- Commit no meio do passo para mostrar início de operação longa: o executor já faz isso em `_note_thought`; manter o mesmo padrão e não commitar no meio de transições.
- Contador de sequência em memória pressupõe um processo servindo a API e o worker (configuração atual); documentar.
- Streaming com `format` JSON no Ollama: conferir que o conteúdo final é igual ao da chamada sem streaming.
- Testes existentes que leem `task.status_changed` ou `run.stalled`: atualizar junto.

## Etapas

- [x] Auditoria e diagnóstico
- [x] Unidade 1
- [x] Unidade 2
- [x] Unidade 3
- [x] Unidade 4
- [x] Unidade 5
- [x] Unidade 6
- [x] Verificação final e estado `concluída`

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/internal/tarefas/2026-10-18-observabilidade-tempo-real.md` | este checklist |

## Notas de retomada

Baseline antes da tarefa: 188 testes passam.
