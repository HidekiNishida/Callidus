# Requisitos, validação do plano, verificação independente e progresso real

Três mecanismos que complementam a decomposição, o contexto e a consolidação descritos em [execucao-autonoma.md](/docs/architecture/execucao-autonoma.md).

## Requisitos rastreáveis

`src/agent/orchestrator/requirements.py`. Sem tabela nova: os requisitos ficam no contrato da raiz (`task_contracts.acceptance_json.requirements`) e a cobertura em `tasks.metadata_json.covers`.

| Campo | Significado |
|-------|-------------|
| `id` | Estável (`R1`, `R2`…); gravado uma vez e reutilizado em passos, replanejamentos e retomadas |
| `description`, `origin` | Texto e de onde veio (`objetivo`, `critérios de aceite`, `contrato`) |
| `criterion` | Critério de aceite |
| `applicability` | `obrigatório`, `não aplicável`, `informativo` ou `bloqueado` (com `blocked_reason`) |
| `evidence` | `change` exige verificador aprovado (teste, sintaxe, arquivo); `answer` aceita a resposta final entregue |
| `refs` | Contratos e artefatos relacionados |

**Origem.** Ao iniciar o run, `ensure_requirements` lê o contrato da raiz. Se estiver vazio, deriva do texto de forma determinística: cada item enumerado do objetivo e cada linha dos critérios de aceite vira um requisito; sem itens, o objetivo inteiro é `R1`. Requisitos definidos por `PUT /tasks/{id}/contract` (campo `acceptance.requirements`) têm precedência.

**Cobertura.** Cada tarefa pode declarar `covers: ["R1", {"req": "R2", "partial": true, "part": "API"}]`. Sem declaração, herda a do pai; a raiz cobre todos. O prompt de decomposição lista os requisitos da etapa (`requirements_block`) e pede `covers` em cada subtarefa.

**Estado** (`requirement_status`), calculado pelas folhas que cobrem o requisito (canceladas e substituídas por replanejamento não contam):

| Estado | Quando |
|--------|--------|
| `uncovered` | Nenhuma folha responsável |
| `failed` / `blocked` | Uma folha responsável parou |
| `pending` | Alguma folha ainda não concluiu com evidência válida |
| `unverified` | Todas concluíram, mas falta evidência proporcional (mudança sem verificador aprovado e atual) |
| `satisfied` | Evidência proporcional válida |
| aplicabilidade | Requisito não obrigatório devolve `não_aplicável`, `informativo` ou `bloqueado` |

Uma tarefa concluída não basta: requisito de mudança só é atendido com evidência de verificador, nunca pela resposta do modelo.

**Cobertura implícita × declarada.** Se nenhuma irmã declara `covers`, toda etapa herda os requisitos do pai (cobertura implícita). Se alguma declara, a etapa sem declaração é apoio e não cobre nada, para que uma etapa genérica não mascare um requisito esquecido. No replanejamento, os requisitos da etapa parada e das irmãs não feitas passam para "Seguir com o plano corrigido".

## Validação do plano antes da execução

`src/agent/orchestrator/plan_validation.py`. Roda logo depois de cada decomposição, sobre as etapas já gravadas (uma única implementação para planos novos e alterados). Todas as regras são determinísticas.

| Regra | Resultado se falhar |
|-------|---------------------|
| Objetivo global e critérios de aceite; requisito obrigatório com critério | incompleto |
| Plano com etapas; cada etapa com resultado esperado | incompleto |
| Requisito obrigatório do pai sem etapa responsável | incompleto |
| Etapa que cobre requisito sem critério verificável (verificação, operação do modelo, resposta final, subsistema ou critério de aceite) | incompleto |
| Cobertura citando requisito inexistente | inconsistente |
| Dependência inexistente, de outro projeto, em tarefa cancelada, para si mesma ou circular | inconsistente |
| Etapa idêntica a outra (título, objetivo, ferramenta e argumentos) | inconsistente |
| Ferramenta inexistente | inconsistente |
| Ferramenta que depende de aprovação, navegador desligado, `metadata.external` | ressalva, etapa listada em `blocked` |
| Requisito que só depende de etapas bloqueadas | ressalva |
| Entrada (`read_file`/`edit_file`) inexistente que nenhuma dependência produz | ressalva |
| Mudança sem verificação declarada (só a implícita) | ressalva |
| Mesmo título com objetivo diferente | ressalva |
| Nenhuma etapa declara `covers` e há vários requisitos | inconclusivo |
| Run passaria de `MAX_TASKS_PER_RUN`; todas as etapas bloqueadas | inviável |

O resultado é o pior entre os achados: `válido`, `válido com ressalvas`, `inconclusivo`, `incompleto`, `inconsistente`, `inviável`. Os três primeiros executam. "Inconclusivo" executa porque não há erro estrutural, mas a cobertura não foi provada; o aceite global por requisito continua exigindo evidência. Uma opinião de modelo sobre cobertura nunca conta como prova.

**Correção e bloqueio** (`validate_and_repair`). Se o plano não pode executar, aplica correções seguras e valida de novo:

- dependências por índice inválidas ou circulares no JSON são removidas antes de gravar (`sanitize_spec`);
- a duplicata é cancelada;
- a dependência em tarefa cancelada é removida;
- ferramenta inexistente vira operação do modelo;
- requisito inexistente sai do `covers`;
- etapa sem critério verificável vira apoio;
- requisito sem responsável ganha a etapa `Atender Rn` (`subsystem`, `covers: [Rn]`), da qual a resposta final passa a depender.

Se ainda não puder executar, nada do plano roda: as etapas são canceladas com `invalid_plan` (ficam no histórico) e o pai vai a `BLOCKED` com `last_failure.cause = invalid_plan`. A categoria é `change_strategy`, ou `external_unavailable` se tudo está bloqueado, ou `operational_limit` se o orçamento estoura. Ação `plan_invalid`. Desbloqueado (`BLOCKED → PLANNING`), o pai é decomposto de novo.

**Versões e revalidação.** `metadata_json.plan_validation` do pai guarda o resultado atual: veredito, achados, cobertura, bloqueadas, correções, veredito inicial, `version` e `fingerprint`. Cada versão gera um evento `plan.validated` com o plano completo. Antes de executar uma etapa, o runner compara a impressão do plano do pai (etapas, cobertura, ferramenta, verificação, dependências) e, se mudou (replanejamento, dependência nova), valida de novo (`plan_revalidated`).

## Verificação independente

Quem executa não aprova o próprio resultado. A resposta do modelo ("pronto, corrigido") não é evidência; só verificadores determinísticos geram evidência (`verification/runner.py`), escolhidos pelo risco ([verificação proporcional](/docs/architecture/execucao-autonoma.md#verificação-proporcional-ao-risco)).

| Nível | Verificador |
|-------|-------------|
| Estrutura e arquivo | `file_contains` (lê o arquivo inteiro, como gravado) |
| Sintaxe | `syntax` (Python via `ast`, JSON); a escrita implícita do modelo usa `file_contains` com `syntax: true` |
| Testes unitários, integração, regressão | `pytest`, `script`, `command` |
| Aceite global | etapa `Verificação global` (`metadata.global_verification` da raiz) e aceite por requisito |

**Evidência persistida** (`evidence`, sem tabela nova; extras em `detail_json`):

| Campo | Onde |
|-------|------|
| Identificador, tarefa, tentativa, momento | `id`, `task_id`, `attempt_id`, `created_at` |
| Verificador e comando | `verifier`, `detail.command` (o spec executado) |
| Resultado e código de saída | `passed`, `detail.state`, `detail.exit_code` |
| Critério avaliado | `detail.criteria` (requisitos cobertos, parciais, critério de aceite da etapa) |
| Artefatos avaliados | `detail.artifacts` (impressão digital) |
| Motivo de falha ou impossibilidade | `detail.reason` |
| Validade | `detail.state = desatualizado`, `previous_state`, `invalidated_at`, `invalidated_reason` |

| Estado | `passed` | Efeito na tarefa |
|--------|----------|------------------|
| `aprovado` | `true` | conclui |
| `reprovado` | `false` | `RETRY_PENDING` (corrigir a implementação, com o motivo no contexto); repetido igual → `BLOCKED` |
| `bloqueado` | `null` | `BLOCKED`: a verificação não rodou (executável ausente, aprovação pendente). Falha de ambiente não é falha da implementação, então não refaz o código. |
| `inconclusivo` | `null` | `BLOCKED`: nunca conta como sucesso |
| `desatualizado` | mantém | deixa de valer; a tarefa reabre e verifica de novo |
| não executado | — | requisito sem evidência (`pending`/`unverified` em `requirement_status`) |

Nenhum resultado é inventado: sem execução não há linha de evidência. Evidência nunca é apagada. Só a mais recente vale, e só se passou, não foi marcada como desatualizada e os arquivos não mudaram.

## Aceite global por requisito

O run só termina como concluído quando cada requisito obrigatório está `comprovado` (`satisfied`), além das condições anteriores (evidências atuais e consolidação sem falha). `não aplicável` e `informativo` não bloqueiam; requisito declarado `bloqueado` bloqueia.

| Estado (`requirements_report`) | Rótulo | Significado |
|--------------------------------|--------|-------------|
| `satisfied` | comprovado | todas as folhas que o cobrem concluíram com evidência proporcional |
| `uncovered` | sem etapa responsável | nenhuma folha viva cobre o requisito |
| `unverified` | concluído sem evidência suficiente | as folhas concluíram, mas falta verificador (mudança) ou resposta final (resposta); "o modelo disse que terminou" cai aqui |
| `pending` | não executado | alguma folha responsável ainda não concluiu ou sua evidência não vale |
| `failed` / `blocked` | reprovado / bloqueado | uma folha responsável parou |

Raiz sem filhas é a própria folha e cobre todos os requisitos.

**Integração.** A etapa `Verificação global` (quando a raiz pede `global_verification`) cobre todos os requisitos obrigatórios. Etapas aprovadas uma a uma não bastam: se a integração reprova ou bloqueia, os requisitos ficam `pending`/`blocked` e o run não conclui.

**Correção localizada** (`correct_requirement_gaps`). No aceite global, se faltar comprovar um requisito, primeiro reabrem-se as tarefas com evidência reprovada ou desatualizada (`reopen_verification_gaps`, só a tarefa afetada e seus ancestrais). Se não houver, cria-se sob a raiz uma etapa por requisito (`Atender Rn` para sem etapa, `Comprovar Rn` para sem evidência), com `covers: [Rn]` e `requirement_fix`, uma vez por requisito. A resposta final é reaberta e passa a depender dela; etapas irmãs comprovadas não são refeitas.

**Relatório parcial.** Se ainda assim faltar, o run para (`run_stalled`) com `consolidated_result_json.requirements` e uma tabela "Requisitos" na mensagem (comprovado, não executado, sem evidência...), além das pendências. Na conclusão, o mesmo relatório fica em `requirements`, com os ids das evidências.

## Progresso real: estagnação, limites, pausa e retomada

Atividade não é progresso: chamada ao modelo, tentativa nova, plano novo ou tarefa "concluída" sem evidência não contam. Progresso é o estado verificável melhorar (`orchestrator/progress.made_progress`: mais tarefas verificadas, ou menos pendências sem perder verificadas), gravado em cada `orchestrator.action`.

**Mesmo erro, comparado normalizado** (`orchestrator/stagnation.py`). Cada falha gravada (`_remember_failure`) leva `signature` (categoria, causa e texto sem números, ids, hashes, aspas e espaços) e `strategy` (ferramenta e argumentos, verificação, modo de operação, `strategy`, objetivo). Falhas seguidas com a mesma assinatura e a mesma estratégia contam como repetição. Mudar a estratégia de forma identificável (outra ferramenta, outros argumentos, `metadata.strategy` com a hipótese) zera a contagem. Reenviar o mesmo pedido com outro texto de erro não zera. O replanejamento compara o motivo também normalizado: sem etapa nova concluída e com o mesmo motivo, ele é recusado.

**Resposta à estagnação** (`RunOrchestrator._check_stagnation`, depois de cada passo). Ao atingir `attempts_per_strategy` repetições:

| Passo | Como |
|-------|------|
| 1. Interromper a repetição | a etapa sai de `RETRY_PENDING` para `BLOCKED` |
| 2. Registrar estado anterior e motivo | `metadata.stagnation` (`previous_status`, assinatura, estratégia, contagem, momento) e evento `run.stagnation` |
| 3–4. Causa provável e tipo | `diagnose`: contexto, planejamento, implementação, ferramenta, configuração, dependência ou verificação, pela causa da falha |
| 5–6. Ação proporcional, reduzir escopo | por tipo: dividir a etapa (contexto), trocar a abordagem (implementação), recuperar a evidência (verificação), corrigir a configuração (configuração) |
| 7–8. Recuperar evidência, atualizar plano e contratos | o replanejamento existente (`replan_under`) recebe a falha `stagnation` com o diagnóstico e carrega a cobertura de requisitos |
| 9. Próxima ação | `metadata.stagnation.next_action` |
| 10. Continuar ou pausar | segue (`stagnation_replan`) só se o tipo admite correção automática e a política de replanejamento aceita; senão o run pausa com o diagnóstico |

**Limites operacionais** (`Settings`, sobrescritos por `config.limits` do run; 0 desliga). São separados das decisões de decomposição e da proteção contra recursão (`max_tree_depth`, `max_tasks_per_run`).

| Chave em `config.limits` | `Settings` | Padrão |
|--------------------------|-----------|--------|
| `attempts_per_strategy` | `max_attempts_per_strategy` | 3 |
| `steps_without_progress` | `max_steps_without_progress` | 60 |
| `seconds` | `max_run_seconds` | 14400 |
| `model_calls` | `max_model_calls_per_run` | 400 |
| `tool_calls` | `max_tool_calls_per_run` | 600 |
| `tokens` (contexto estimado) | `max_tokens_per_run` | 5 000 000 |
| `replans` (replanejamentos e decomposições) | `max_replans_per_run` | 80 |

`max_attempts_per_task` continua valendo por tarefa.

**Pausa.** Antes de cada passo, `limit_reached` mede o trecho atual do run (desde o início ou a última retomada). Se um limite foi atingido, `_pause_run`:

- põe o run em `paused`, sem mudar o estado de nenhuma tarefa;
- grava em `metadata.pause` da raiz o limite, o valor, o máximo, o motivo, a próxima ação, o progresso, as pendências e os requisitos (e o diagnóstico, se veio de estagnação);
- escreve a mensagem "Não concluído" com "Próxima ação" e registra o evento `run.paused`.

Passo em run pausado não faz nada (`run_paused`).

**Retomada.** `POST /runs/{id}/resume` (`RunService.resume_run`; 409 se o run não está pausado):

- volta o run a `active` e move a pausa para `metadata.pauses`;
- registra `run.resumed`, e a partir dele os limites recomeçam a contar;
- com `retry_blocked=true`, etapas bloqueadas voltam a `PLANNING` (depois de corrigida a causa de fora).

O trabalho comprovado não é refeito. As evidências desatualizadas são reabertas no aceite global.
