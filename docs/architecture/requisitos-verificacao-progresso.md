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
