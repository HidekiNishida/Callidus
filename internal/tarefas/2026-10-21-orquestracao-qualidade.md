# Checklist: orquestração de qualidade, disposição e feed

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-21 |
| Atualizado em | 2026-10-21 |
| Agente / tarefa | evolução integrada da orquestração |
| Regras consultadas | [Hub](/docs/regras/README.md) · [AGENTS.md](/AGENTS.md) |

## Objetivo

Integrar ao ciclo existente o contrato de qualidade, a escolha entre executar, investigar, decompor e replanejar, e uma explicação do feed ligada a esses fatos.

## Próxima ação

Nenhuma nesta tarefa. A medição comparativa com o modelo local fica para uma rodada de avaliação.

## Etapas

- [x] Auditar orquestrador, requisitos, estratégia, eventos e feed
- [x] Gravar contrato de qualidade no aceite da raiz e herdar o recorte
- [x] Aplicar a disposição no lugar do atomizador quando a etapa já é um passo ou ainda não localiza o alvo
- [x] Publicar `work.explained` e mostrar a frase na atividade
- [x] Testar contrato, disposição, feed e regressão do plano raso e da profundidade
- [x] Documentar limites, inclusive a ausência de comparação com o modelo local

## Evidência

- `python -m pytest tests/test_quality_disposition.py tests/test_progress_metrics.py::test_simple_question_is_not_over_decomposed tests/test_functional_depth.py tests/test_strategy_and_decomposition.py tests/test_atomizer.py` — 22 passed
- `python -m pytest tests/test_e2e_orchestrator.py tests/test_decompose_loop.py tests/test_web_frontend.py` — passou; `test_discovers_common_agent_guides` passou fora do sandbox
- `node --test tests/web/work-explained.test.mjs` — 2 passed
- Links e Markdown dos documentos tocados — sem problema

## Pendência

A interface ao vivo não foi exercitada com uma run nova: o tradutor do evento foi testado no módulo, e o processo que já escuta na porta 8765 precisa ser reiniciado para servir este código.
