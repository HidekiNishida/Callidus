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

Desative em testes com `Settings(enable_background_worker=False)`.
