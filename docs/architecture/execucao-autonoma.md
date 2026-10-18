# Execução autônoma em segundo plano

Runs com `config_json.autonomous = true` são avançados pelo worker asyncio (`autonomous_worker.py`), iniciado no lifespan da API quando `ENABLE_BACKGROUND_WORKER` (padrão `true`).

## Ciclo

1. Listar runs `ACTIVE` com flag autônoma.
2. `RunOrchestrator.step` por run (commit por tick).
3. Intervalo configurável (2s).

## Controles

- `POST /runs/{id}/autonomous/enable`
- `POST /runs/{id}/autonomous/disable`
- Checkbox **Autônomo** na UI ao iniciar run.
- Pausar/cancelar run interrompe avanço útil mesmo com flag ligada.

## Recuperação

Estado em SQLite; após reinício da API o worker retoma runs ativos autônomos.

## Término do run

Quando nenhuma tarefa pode avançar (e o replanejamento não tem mais o que fazer), o run nunca fica em espera infinita:

- **Concluído** só se a raiz está `COMPLETED`, todos os descendentes terminaram e `evaluate_global_acceptance` passou. Verificação concluída sem evidência é reaberta (`global_verify_reopen`).
- **Parado com pendências** (`_stall_run`) em qualquer outro caso: run `failed`, raiz `BLOCKED` (recuperável: `BLOCKED → PLANNING`), relatório com `achieved=false`, `pending` (etapa, status, motivo) e `final_answer` em "## Não concluído". Evento `run.stalled`; ação `run_stalled`. O que já concluiu fica salvo.

`consolidate_parent` nunca conclui um pai com filho falho: devolve `achieved=false` e `pending`. Pai em execução com filho falho vai a `BLOCKED` (`blocked_dependency/dependency_failed`), o que aciona o replanejamento do nível de cima.

## Falhas categorizadas

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
