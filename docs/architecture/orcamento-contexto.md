# Orçamento de contexto e de execução

O Callidus separa duas contas que antes se misturavam.

A **janela** é o que cabe numa chamada (`ModelProfile`: `context_limit`, `input_budget`, `output_reserve`). A **execução** é a soma de todas as inferências da run. Uma chamada pode caber na janela e, ainda assim, estourar o teto acumulado.

## 🏗️ Contabilização

Cada inferência que passa por `observed_chat` dentro de uma run grava uma linha em `inference_records`, com a chave `run_id:output_id`. Gravar de novo a mesma chave não soma outra vez.

| Campo | Significado |
|-------|-------------|
| `prompt_tokens`, `completion_tokens` | O que o provedor informou. Ausência fica `NULL`, não zero |
| `estimated_*` | Estimativa local feita antes da chamada (~4 caracteres por token) |
| `measurement` | `exact`, `estimate`, `partial` ou `unavailable` |
| `reasoning_tokens`, `cache_*` | Informados à parte. Não entram de novo no total de entrada ou de saída |
| `cost_usd` | Só existe quando `config.prices` traz preço por milhão para o provedor |

O ciclo de ferramentas chama o modelo várias vezes. Cada chamada vira uma linha. O metadado `task.metadata_json.usage` é reescrito pela soma dessas linhas, para a última resposta não apagar as anteriores.

`usage_since` usa essa soma. Execução antiga, sem nenhuma linha, ainda cai na soma dos snapshots, e `tokens_source` marca `snapshot_estimate`.

Fora de uma run (`observe` inativo) a chamada não entra no teto. O diagnóstico `POST /debug/chat/ollama` é esse caso: não há execução para debitar.

## ⚙️ Controle antes da chamada

`assess_inference` roda dentro de `observed_chat`, antes do provedor.

O teto de tokens é `limits.tokens` (padrão `max_tokens_per_run`) mais `config.budget_grants`. A retomada **não** multiplica esse teto. Uma autorização nova é `POST /runs/{id}/budget-grant`, com quantidade e motivo, gravada no run e em `budget.granted`.

A reserva (`budget_reserve_ratio`, padrão 0,10) fica de fora das finalidades de trabalho. Finalidades de conclusão (`final_answer`, `verify`, `verification`, `consolidation`, `closing`, `checkpoint`, `summary`) podem usá-la até o teto autorizado.

Faixas sobre o teto autorizado, configuráveis em `Settings` ou em `config.budget`:

| Faixa | Padrão | Efeito na chamada que não é de conclusão |
|-------|--------|------------------------------------------|
| até `warn` | 70% | segue |
| até `reduce` | 85% | segue e marca consumo elevado |
| até `stop` | 90% | segue, marca `context_pressure=reduce` e emite `budget.pressure` |
| acima, ou se a estimativa da próxima chamada invadir a reserva | | pausa a run, sem chamar o modelo |

A pausa reutiliza o caminho já existente (`run.paused`): estado, pendências e próxima ação ficam na raiz. O trabalho comprovado não é refeito. Retomar não devolve o que já foi gasto.

Chamadas, tempo e custo conhecido também podem pausar a chamada não essencial. Custo desconhecido não é tratado como zero e não bloqueia.

## 🧠 Memória

Três níveis em `memory_records`:

1. `operational` — resumo curto (objetivo, aceite, estado, próximo passo, arquivos, último erro). É o que volta no prompt e na retomada.
2. `task_detail` — decisão ou descoberta. A busca é `GET /tasks/{id}/memory`.
3. `artifact` — referência a snapshot ou log, com um diagnóstico curto.

O pai recebe `child_summary`: estado, status e a referência. Não recebe o histórico do filho.

A decomposição não trata metadado inchado como complexidade. Etapa de um resultado só continua um passo; a divisão segue o que já estava em `decide_disposition` (vários itens, investigação, profundidade).

## 🔍 Painel

A aba Contexto mostra duas contas:

- **Chamada atual** — janela configurada (da execução, ou o padrão do processo), ocupação dessa janela, estimativa do snapshot, uso informado da última inferência, diferença entre os dois e as categorias gravadas em `categories_json`.
- **Consumo acumulado** — soma do livro-razão, reserva, saldo, teto e finalidade.

Número ausente aparece como indisponível. A estimativa de janela não é rotulada como uso do provedor.

## 🧪 Limitações

- Não houve medição comparável de tokens por tarefa concluída antes e depois, com o mesmo modelo e os mesmos pedidos. A correção torna a conta confiável; não afirma economia.
- Provedor que não informa uso deixa a linha `unavailable`. O controlador usa a estimativa local guardada na mesma linha para não ficar cego, e o painel mostra a qualidade.
- Preço não é inventado. Sem `config.prices`, o custo fica indisponível.
- A soma histórica que vivia só em `metadata.usage`, antes desta tabela, não é reconstituída. A primeira inferência nova da tarefa passa a valer o livro-razão.

Código: [ledger.py](/src/agent/orchestrator/ledger.py), [budget_gate.py](/src/agent/orchestrator/budget_gate.py), [observed.py](/src/agent/providers/observed.py), [operational.py](/src/agent/memory/operational.py).
