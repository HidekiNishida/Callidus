# Checklist: Hierarquia de Agentes Recursiva, Executor Compartilhado e Consultas Sob Demanda

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-20 |
| Atualizado em | 2026-10-20 |
| Agente / tarefa | Evolução arquitetural: agentes lógicos, execução sequencial, estado persistente, consultas entre gerações — **e** etapa de validação/otimização |
| Regras consultadas | [Hub](/docs/regras/README.md), [principios.md](/docs/regras/principios.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [readmes-pastas.md](/docs/regras/readmes-pastas.md), [documentacao.md](/docs/regras/documentacao.md), [checklists-tarefas.md](/docs/regras/checklists-tarefas.md), [verificacao-final.md](/docs/regras/verificacao-final.md) |

## Objetivo

Evoluir o Callidus para coordenar uma hierarquia recursiva de agentes com estado
persistente, execução estritamente sequencial no executor compartilhado e consultas
entre agentes sob demanda — sem depender de mais memória ou de mais modelos
simultâneos. Na segunda etapa: validar a implementação, corrigir o que a medição
revelar e documentar o escopo real das garantias.

## Próxima ação

Nenhuma — tarefa concluída. Evoluções futuras sugeridas (não implementadas, por não
haver necessidade demonstrada): serialização entre processos via trava externa
(universal), e indexação semântica das descobertas para as perguntas indiretas que a
busca lexical não alcança.

## Etapas

### Implementação

- [x] Diagnóstico da arquitetura existente (agentes, delegação, inferência, persistência, agendamento, testes)
  - 454 testes como linha de base; hierarquia de tarefas já era recursiva (`tasks.parent_id`, profundidade 16)
  - Lacunas: sem entidade de agente, sem entidade de execução, sem exclusividade de inferência, sem suspensão por agente, sem consultas
- [x] Executor compartilhado de inferência (`src/agent/services/executor.py`)
  - Limite por processo (padrão 1), métricas de concorrência/espera, cancelamento sem slot órfão
  - Exclusividade no contrato do provedor (`LLMProvider.chat` → `_chat`), cobrindo todas as rotas de chamada
- [x] Entidades persistentes de agente, execução e consulta (`agents`, `agent_executions`, `agent_queries`)
- [x] Estados e transições (`src/agent/domain/agent_enums.py`, `agent_lifecycle.py`) — transições inválidas são erro
- [x] `AgentService`: identidade estável, `start_execution`, `suspend`, `resume`, `checkpoint`, `findings`, `discard` com verificações
- [x] `QueryService`: protocolo de consulta com correlação, tentativas, anti-ciclo, resolução pelo estado persistido antes da inferência
- [x] Busca descendente: a resposta alcança a evidência do neto sem repassar histórico
- [x] `AgentScheduler`: fila por eventos, uma operação por vez, sem espera que consome token
- [x] Integração: decomposição cria agentes filhos; consolidação importa resultados como descobertas; runner sincroniza agente ↔ tarefa
- [x] Worker autônomo: descoberta por consulta ao SQLite (sem inferência) e execução via escalonador
- [x] API HTTP da hierarquia (`/agents/*`, `/projects/{id}/agents`, `/metrics/resources`)
- [x] Documentação: `docs/architecture/hierarquia-agentes.md` + hub, modelo de dados, limitações, README raiz e READMEs de pasta

### Validação e otimização

- [x] Suíte completa reexecutada: 454 → 522 → **560 testes**, todos verdes
- [x] Revisão de todos os caminhos de inferência: 6 chamadas, todas pelo contrato do provedor; nenhum `_chat` called diretamente
- [x] **Brecha encontrada e corrigida**: semáforo por laço permitia 3 inferências simultâneas em 3 threads → contador global de processo com despertar entre threads
- [x] Escopo documentado e medido: sessões ✔, threads ✔, **processos ✖** (2 processos inferem em paralelo — medido)
- [x] Ollama real (`llama3.2:3b`): latência, chamadas, contexto, RSS/VRAM antes–durante–depois de suspender/retomar
- [x] **Defeito corrigido**: acentos quebravam a tokenização lexical ("cálculo" nunca casava)
- [x] **Defeito corrigido**: sentinela `SEM_EVIDENCIA` frágil (modelo 3B respondeu "SEMA INFORMAÇÃO FALTA") → reconhecimento por intenção
- [x] **Defeito corrigido**: caminho de inferência não enxergava a descendência → contexto da subárvore + verificação de lastro
- [x] Casamento lexical endurecido após medir 1 falso positivo adversarial → 0 falsos positivos
- [x] Falhas testadas em execução, suspensão, retomada, consulta e descarte (sem perda de estado nem duplicação)
- [x] Resultado, evidência e artefato verificados após suspender, concluir e descartar
- [x] Scripts de medição: `medir-hierarquia.py`, `avaliar-consultas.py`, `medir-ollama.py`
- [x] Verificação final: código ↔ docs ↔ checklists ↔ regras

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/services/executor.py` | Executor compartilhado (escopo de processo) |
| `/src/agent/services/agent_service.py` | Ciclo de vida do agente lógico |
| `/src/agent/services/query_service.py` | Consultas entre agentes + verificação de lastro |
| `/src/agent/services/agent_scheduler.py` | Escalonador por eventos |
| `/src/agent/api/agent_routes.py` | Endpoints da hierarquia |
| `/src/agent/domain/agent_enums.py` | Estados de agente, execução e consulta |
| `/src/agent/domain/agent_lifecycle.py` | Transições válidas |
| `/docs/architecture/hierarquia-agentes.md` | Documento da evolução |
| `/tests/test_agent_hierarchy_e2e.py` | Cenário de três gerações ponta a ponta |
| `/tests/test_executor_scope.py` | Trava contra regressão do limite de inferência |
| `/tests/test_agent_resilience.py` | Falhas e acessibilidade de resultado/evidência |
| `/scripts/medir-hierarquia.py` | Medição de contexto e inferências |
| `/scripts/avaliar-consultas.py` | Avaliação do casamento lexical com gabarito |
| `/scripts/medir-ollama.py` | Medição com modelo local real |

## Notas de retomada

O executor compartilhado é o ponto único de exclusividade: qualquer novo caminho de
inferência deve chamar `provider.chat` (nunca `_chat`) para herdar a garantia. A
hierarquia de agentes acompanha a de tarefas — `ensure_agent(task_id)` cria o agente
sob demanda e é idempotente. Consultas respondem do estado persistido antes de gastar
inferência; a métrica `queries.answered_from_state` mede esse ganho. A verificação de
lastro (`grounded`) é lexical e conservadora: em caso de dúvida, marque sem lastro
em vez de afirmar.
