# Checklist: narração do agente em tempo real

Streaming real da fala pública do modelo até a Atividade do agente.

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-11-02 |
| Atualizado em | 2026-11-02 |
| Agente / tarefa | Claude — G10 (narração em tempo real) e parte do G11 |
| Regras consultadas | [Hub](/docs/regras/README.md), [AGENTS.md](/AGENTS.md) |

## 🎯 Objetivo

A pessoa acompanha o agente explicando o que faz, palavra por palavra, na linha do tempo, com o
texto vindo dos fragmentos reais da inferência — sem inferência extra, sem simular digitação e
sem expor raciocínio ou argumentos de ferramenta.

## Próxima ação

Nenhuma nesta atividade; o que falta do G10 está em [gaps.md](/docs/progresso/gaps.md#g10-streaming-de-tokens-na-interface).

## 🔄 Etapas

- [x] Auditoria: provedores já transmitiam; a UI ignorava `agent.output.delta` e escondia a narração nos detalhes
- [x] Achado: streams de OpenAI-compatível, llama.cpp, Anthropic e Gemini descartavam chamadas de ferramenta
- [x] `observability/narration.py`: filtro incremental e eventos `agent.narration.*`
- [x] Provedores: ferramentas remontadas e raciocínio separado nos streams; parte `thought` do Gemini fora do texto
- [x] Barramento: narrações em curso na foto ao vivo (reconexão)
- [x] Interface: `NarrationEntry`, `mergeNarration`, semente ao vivo, "Novas atividades"
- [x] Testes A, C–J automatizados; B com Ollama real (`lab/medir_narracao.py`)
- [x] Regressão visual no navegador: claro, escuro, celular, interrompida, rolagem
- [x] Documentação: arquitetura, READMEs, limitações, `resume.md`, progresso
- [x] `python scripts/ci.py` verde
- [x] Avaliação ampla antes/depois (`lab/avaliar.py`, `gpt-oss:20b`): sem regressão

## Bloqueios

- Nenhum.

## Artefatos

- [narracao-tempo-real.md](/docs/architecture/narracao-tempo-real.md)
- [`src/agent/observability/narration.py`](/src/agent/observability/narration.py)
- [`web/static/assets/app/components/narration.js`](/web/static/assets/app/components/narration.js)
- [`tests/test_narration_stream.py`](/tests/test_narration_stream.py), [`tests/web/live-narration.test.mjs`](/tests/web/live-narration.test.mjs)
- [`lab/medir_narracao.py`](/lab/medir_narracao.py)
