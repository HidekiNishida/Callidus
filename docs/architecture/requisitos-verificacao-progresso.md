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
