# Execução autônoma em segundo plano

O worker autônomo: o laço em segundo plano e o escalonador.

Runs com `config_json.autonomous = true` são avançados pelo worker asyncio (`autonomous_worker.py`), iniciado no lifespan da API quando `ENABLE_BACKGROUND_WORKER` (padrão `true`).

## 🔄 Ciclo

1. Listar runs `ACTIVE` com flag autônoma.
2. `RunOrchestrator.step` por run (commit por tick).
3. Intervalo configurável (2s).

## 🧠 Controles

- `POST /runs/{id}/autonomous/enable`
- `POST /runs/{id}/autonomous/disable`
- Checkbox **Autônomo** na UI ao iniciar run.
- Pausar/cancelar run interrompe avanço útil mesmo com flag ligada; passo em run pausado não faz nada.
- `POST /runs/{id}/resume` retoma um run pausado (por pedido ou por [limite operacional](/docs/architecture/requisitos-verificacao-progresso.md#progresso-real-estagnação-limites-pausa-e-retomada)); `?retry_blocked=true` devolve etapas bloqueadas ao planejamento.

## 🔄 Recuperação

Estado em SQLite; após reinício da API o worker retoma runs ativos autônomos. Nada vive só em memória: reabrir o banco e chamar `step` continua do ponto salvo.

A evidência de verificação guarda em `detail_json.artifacts` a impressão digital (`verification/fingerprint.py`) dos arquivos que avaliou (o arquivo do `file_contains`/`script`, a pasta do `pytest`/`command`; bancos SQLite e caches ficam fora). Vale apenas a evidência **mais recente** da tarefa, e só se passou e os arquivos não mudaram. Escrita sem verificação declarada grava a implícita em `metadata_json.implicit_verification`, que passa pela mesma regra.

Na retomada, se um arquivo mudou depois da verificação, a aceitação global recusa ("evidência ausente ou desatualizada") e `reopen_verification_gaps` devolve a tarefa a `VERIFYING` com `last_failure.cause = stale_evidence`: o estado atual é verificado de novo antes de repetir qualquer operação, e só se reprovar a operação é refeita, com o motivo no contexto. Evidência antiga nunca é apagada. Ao refazer, o contexto lê os arquivos-alvo do disco naquele momento.

## 🔄 Término do run

Quando nenhuma tarefa pode avançar (e o replanejamento não tem mais o que fazer), o run nunca fica em espera infinita:

- **Concluído** só se a raiz está `COMPLETED`, todos os descendentes terminaram e `evaluate_global_acceptance` passou. Verificação concluída sem evidência é reaberta (`global_verify_reopen`).
- **Parado com pendências** (`_stall_run`) em qualquer outro caso: run `failed`, raiz `BLOCKED` (recuperável: `BLOCKED → PLANNING`), relatório com `achieved=false`, `pending` (etapa, status, motivo) e `final_answer` em "## Não concluído". Evento `run.failed` com `kind: stalled`; ação `run_stalled`. O que já concluiu fica salvo.

`consolidate_parent` nunca conclui um pai com filho falho: devolve `achieved=false` e `pending`. Pai em execução com filho falho vai a `BLOCKED` (`blocked_dependency/dependency_failed`), o que aciona o replanejamento do nível de cima.

**Etapa cancelada é trabalho que não foi feito.** A consolidação distingue o cancelamento
**previsto** do que sobrou pelo caminho:

| Cancelamento | Efeito |
|--------------|--------|
| Previsto (`superseded_by_replan`, `cancelled_reason` = `duplicate` / `invalid_plan`) | outra etapa assume o trabalho; o pai pode seguir |
| Não previsto | pendência: o pai **não** conclude como se o plano inteiro tivesse sido cumprido |

O replanejamento marca os irmãos que cancela com `superseded_by_replan` — sem a marcação, o pai
ficava `BLOCKED` mesmo com o plano novo já concluído.

## 🎯 A resposta final carrega os fatos

O texto que o modelo escreve para a pessoa é curto e, por desenho, não cita verificações. Mas
quem lê não pode depender do julgamento do modelo para saber se os testes passaram: uma resposta
que afirma sucesso enquanto a suíte reprova é uma conclusão falsa.

Por isso a resposta final ganha um **rodapé determinístico** (`closing.verification_footer`):
as verificações que passaram, as que reprovaram e as inconclusivas, com o resumo de cada uma, e
as execuções que reprovaram. Ele não depende do modelo e é escrito a partir das evidências
persistidas. Medido em 20/10/2026: no cenário de verificação reprovada, o texto do modelo
reportava sucesso com a suíte vermelha; com o rodapé, a reprovação aparece.

## 🔐 Permissões ao pelo do pedido

"Não altere nenhum arquivo do projeto" é uma restrição do pedido, e restrição vira **permissão**:

- A estratégia (`strategy.is_read_only_request`) reconhece a restrição negativa e a marca na raiz.
- A marca **desce** com a decomposição, com o replanejamento, com a decomposição adaptativa e
  com a etapa de comprovação de requisito (`consolidation.inherits_read_only`).
- Uma etapa somente leitura recebe só as ferramentas de **inspeção** no ciclo de ferramentas.
- A escrita é **recusada antes de tocar o disco** nos três caminhos: chamada de ferramenta durante
  o ciclo, JSON com `path`/`content` e etapa de plano com `tool: write_file`. A recusa vira o
  resultado da etapa (o modelo respondeu, o arquivo não mudou) — bloquear a etapa faria o
  sistema repetir o mesmo pedido para sempre.

No mesmo cenário de 20/10/2026, o agente alterava `app.py` apesar do pedido; com a permissão, o
arquivo ficou intacto e o run concluiu reportando a reprovação da suíte.

## 🧪 Verificação proporcional ao risco

| Etapa | Verificação |
|-------|-------------|
| Leitura (`list_dir`, `read_file`, busca) | Nenhuma; conclui sem evidência. |
| Escrita do modelo sem verificação declarada | Implícita: `file_contains` com o início do que foi gravado; gera evidência ligada à tentativa. |
| Etapa com `metadata.verification` | A declarada (pytest, script, comando, `file_contains`). |
| Verificação inconclusiva (`acceptance_manual`) | Nunca aprova: a tarefa vai a `BLOCKED`. |

Folha com metadados mas sem ação (`tool`, `verification`, `model_operation`, `final_answer`, `mcp_tool`) vira operação de modelo, em vez de passar por `skipped_to_verify` e concluir sem ter feito nada.

## 🔄 Replanejamento

`replan_under` roda no início de cada passo e aplica `replan_decision` ao primeiro filho parado (BLOCKED/FAILED) ainda não substituído:

| Situação | Decisão |
|----------|---------|
| Falha `configuration` ou `external_unavailable` | Não replaneja: um plano novo não instala programa nem aprova ação. Grava `replan_refused` e o run para explicando. |
| Orçamento da linhagem esgotado (`REPLAN_BUDGET = 3`) | Não replaneja. |
| Último replanejamento sem etapa nova concluída e com o mesmo motivo | Não replaneja (sem progresso). |
| Demais (`recoverable`, `change_strategy`, `operational_limit`, `blocked_dependency`, sem categoria) | Replaneja. |

Ao replanejar: irmãos pendentes são cancelados, o que concluiu fica; o filho parado é marcado `superseded_by_replan` (BLOCKED vira CANCELLED) e deixa de contar como pendência; entram "Ver o que ainda falta" e "Seguir com o plano corrigido", um nó `subsystem` que é decomposto de novo com o que já foi feito, o motivo da parada e o pedido de outra abordagem. Esse nó herda `replan_count`, então replanejamentos aninhados dividem o mesmo orçamento.

## 🧪 Profundidade funcional

Não há profundidade máxima de decomposição. Uma etapa é dividida enquanto não for executável (`executable_leaf`, atomizador, plano que não copia os irmãos). A proteção contra recursão é separada da decisão de dividir (`_recursion_guard`) e só age quando a árvore cresce sem fim:

| Proteção | Configuração |
|----------|--------------|
| Título ou objetivo igual ao de uma etapa acima | sempre |
| Profundidade de segurança | `MAX_TREE_DEPTH` (padrão 16) |
| Tarefas no run | `MAX_TASKS_PER_RUN` (padrão 400) |

Ao acionar, a etapa é executada como operação de modelo, sem nova divisão, e o motivo fica em `metadata_json.recursion_guard`.

## 📊 Progresso e métricas

Progresso é estado verificável, não atividade (`orchestrator/progress.py`):

- `progress_state` conta, sob a raiz, as etapas `verified` (concluídas com evidência válida e atual, ou sem verificação exigida), `pending` (não assentadas), `failed` e `blocked` (ainda não substituídas).
- `made_progress(antes, depois)`: há progresso quando `verified` sobe, ou quando `pending` cai sem `verified` cair. Decompor, chamar o modelo de novo ou repetir uma ferramenta não conta.

Cada evento `orchestrator.action` grava `payload.progress`. `GET /runs/{id}/metrics` (`MetricsService.run_metrics`) deriva daí e das tabelas existentes, sem tabela nova:

| Bloco | Conteúdo |
|-------|----------|
| `tree` | tarefas, profundidade máxima, contagem por status, reabertas |
| `decompositions`, `replans` | ações `decomposed` e `replanned` |
| `attempts` | total, por tipo, máximo por tarefa, estratégias (prompts distintos), prompts repetidos, saídas repetidas |
| `tokens` | estimados nos snapshots e informados pelo provedor (`usage`) |
| `omitted_context` | componentes de contexto omitidos, por nome |
| `errors_by_category` | falhas das tentativas por categoria |
| `time` | início, último evento e duração |
| `evidence` | aprovadas, reprovadas, inconclusivas, desatualizadas |
| `progress` | estado atual, passos e chamadas de modelo desde o último progresso |
| `requirements` | total, comprovados, ids sem comprovação, contagem por estado (o aceite por requisito; nenhuma pontuação o substitui) |
| `stagnation` | estagnações detectadas, erros repetidos (mesma assinatura e estratégia), máximo de tentativas por estratégia, replanejamentos recusados |
| `pauses`, `resumes` | motivo, limite e próxima ação de cada pausa; quantas retomadas |
| `artifacts_validated` | arquivos cobertos por evidência aprovada e atual |

## ⚠️ Falhas categorizadas

Toda tentativa que falha é classificada por `src/agent/domain/failures.py` em **categoria** (o que fazer) e **causa** (o que houve):

| Categoria | Significado | Exemplos de causa |
|-----------|-------------|-------------------|
| `recoverable` | Corrigir localmente e tentar de novo, com o motivo no contexto | JSON malformado, trecho não encontrado, pytest reprovado |
| `change_strategy` | Repetir igual não resolve: reduzir, dividir ou trocar abordagem | resposta cortada, contexto acima do orçamento, saída repetida, ferramenta desconhecida |
| `blocked_dependency` | Depende de tarefa que falhou | dependência falha |
| `external_unavailable` | Falta algo de fora (pessoa, servidor, dado) | aprovação pendente, provedor fora do ar, verificação inconclusiva |
| `configuration` | Ambiente mal configurado | executável ausente, navegador desligado |
| `operational_limit` | Limite atingido | timeout, tentativas esgotadas |

A falha vai para `error_message` da tentativa, para o evento `attempt.recorded` (`payload.failure`) e para `metadata_json.last_failure` / `failures` (últimas 5) da tarefa. A resposta de `step` traz `failure`. Tentativa de modelo só conta como sucesso depois que o JSON foi validado. A evidência de verificação guarda `attempt_id`.

Desative em testes com `Settings(enable_background_worker=False)`.