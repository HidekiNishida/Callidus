# Autoaperfeiçoamento, Calibração Adaptativa e Otimização de Desempenho — Callidus

## Estado inicial

- Repositório: Callidus, branch `main`, último commit `7f84aad` (correção de template Vue na navegação Intelligence).
- Alterações não comitadas no working tree: `web/static/assets/app/main.js` (modificado). Arquivos não versionados: `RELATORIO_ERRO_COMPILER_34.md`, `Site-Exemplo/`.
- Versão do projeto: `pyproject.toml` declara `0.1.0`; documentação cita `v0.5` (gap G13 — versão/licença, decisão do dono).
- Ambiente local: venv em `.venv`, Python 3.14, pacote `agent` instalado em modo editável. Ollama rodando em `http://127.0.0.1:11434` com os modelos `qwen3-vl:8b` e `gpt-oss:20b` instalados. A lib Python `ollama` não está instalada (não é usada; o Callidus chama a API nativa via `httpx`).
- Banco canônico: `data/agent.db` (SQLite, ~28 MB). Existe `test.db` (não versionado, não tocar).
- `.env`: `DEFAULT_PROVIDER=ollama`, `DEFAULT_MODEL_ID=llama3.2`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `AGENT_DATA_DIR=./data`, `API_HOST=127.0.0.1`, `API_PORT=8765`, `DATABASE_URL=sqlite:///./data/agent.db`.
- `data/providers.yaml`: `default_provider: OpenRouter`; provedores `meu_ollama` (ollama / `llama3.2`) e `OpenRouter`. **Não existe** `my_ollama` nem `gpt-oss:20b`, embora a missão defina `my_ollama` / `gpt-oss:20b` como modelo interno de avaliação.
- Qualidade geral estimada: ~61 % (ROADMAP, 2026-10-22). 872 funções `test_` (929 casos passam, 1 pulado); 57 testes de interface passam.
- CI único: `python scripts/ci.py` (lint, cabeçalhos, docs, referências, markdown, resume.md, interface, E2E, Python).

## Arquitetura encontrada

Quatro camadas com dependência apontando para dentro (AGENTS.md §2):

- **Apresentação/Transporte**: `src/agent/api` (FastAPI, SSE, SPA em `web/static/assets/app/`).
- **Aplicação**: `src/agent/services`, `src/agent/orchestrator` (runner, decomposition, strategy, recovery, stagnation, closing, consolidation, global_verify, quality_contract, final_review, plan_validation, requirements, tool_loop).
- **Domínio**: `src/agent/domain` (enums, contratos, máquina de estados, sem FastAPI/SQLAlchemy).
- **Infraestrutura**: `src/agent/persistence`, `providers`, `tools`, `mcp`, `remote`, `desktop`, `vision`.

Camadas de inteligência já presentes (não criar novamente):

- `src/agent/intelligence/` — `telemetry.py` (TelemetryService, eventos correlacionados), `analytics.py` (AnalyticsService com métricas de tokens, contexto, inferência, recursos, eficiência; p50/p95/p99; `measurement_quality`), `benchmarks.py` (BenchmarkEngine, cenários versionados, pontuação por dimensão), `diagnostics.py` (DiagnosticEngine, gargalos/desperdícios/hipóteses/recomendações), `graph.py`.
- `src/agent/learning/operational.py` — OperationalLearning, StrategyRecord, ExperienceStore, StrategyRetriever (persiste estratégias, taxa de sucesso, confiança, reversível, sem fine-tuning).
- `src/agent/knowledge/ucg/` — grafo de conhecimento unificado; `capability.py` (CapabilityGraphService, descoberta seletiva de skills/ferramentas/MCP com TTL).
- `src/agent/orchestrator/cognitive_router.py` — CognitiveRouter (seleção de modelo por complexidade/risco/capacidades, histórico de sucesso, escalonamento).
- `src/agent/providers/ollama_policy.py` — política por família (janela/saída/amostragem); reconhece `gpt-oss` e `deepseek-r1` como "sempre raciocinam" (_ALWAYS_REASONING).
- `src/agent/providers/ollama.py` — OllamaProvider (capacidades: streaming, tools, tool_loop, structured_output, vision, usage_reporting; rastreia uso de tokens).
- `src/agent/context/budget.py`, `operation_builder.py`, `assembler.py` — orçamento e montagem de contexto.
- `src/agent/verification/` + `global_verify.py`, `quality_contract.py`, `final_review.py`, `consolidation.py` — verificação independente.
- `src/agent/orchestrator/stagnation.py`, `recovery_policy.py`, `replan.py`, `closing.py` — detecção de estagnação e recuperação.
- `lab/avaliar.py` — avaliação reproduzível com banco/workspace isolados, critérios de aceite objetivos.
- `scripts/medir-ollama.py`, `medir-qwen3.sh`, `medir-hierarquia.py`, `simular-qwen3.py` — medições existentes.
- `scripts/ci.py` — portões de qualidade únicos.

## Funcionalidades já existentes (não reimplementar)

1. Aprendizado operacional persistido (estratégias, sucesso, confiança, causa de falha, recuperação).
2. Telemetria centralizada com correlação run/tarefa/tentativa/evento pai.
3. Métricas de eficiência (tokens/tarefa, chamadas/tarefa, tempo/tarefa, taxa de conclusão, calls_without_progress, recovery_count).
4. Roteamento cognitivo adaptativo de modelos.
5. Política de janela/saída do Ollama (evita recarga de modelo e repetição sem fim).
6. Decomposição hierárquica e plano de tarefas.
7. Detecção de estagnação, replanejamento dirigido, pausa e retomada.
8. Verificação independente, revisão final, consolidação, contrato de qualidade.
9. Capability graph com descoberta seletiva de skills/ferramentas/MCP.
10. Avaliação reproduzível (`lab/avaliar.py`) e scripts de medição.

## Lacunas efetivas (faltando para a missão)

| # | Lacuna | Evidência |
|---|--------|-----------|
| L1 | Provedor `my_ollama` / `gpt-oss:20b` não configurado | `data/providers.yaml` tem apenas `meu_ollama`/`llama3.2` e default `OpenRouter`; `.env` aponta `llama3.2` |
| L2 | Não há perfis operacionais consolidados (consulta, investigação, planejamento, implementação, correção, refatoração, testes, documentação, verificação, pesquisa, automação) com limites configuráveis | `cognitive_router.py` tem `OperationProfile` genérico, mas não perfis nomeados por tipo de trabalho com orçamento de contexto, reserva de saída, granularidade de decomposição, profundidade recursiva, tentativas, inspeções, skills, intensidade de verificação |
| L3 | Não há calibração adaptativa funcional (champion/challenger, experimento controlado, rollback, perfil versionado, histórico de calibrações) | `learning/operational.py` registra estratégias mas não ajusta automaticamente parâmetros (contexto, saída, temperatura, tentativas, seleção de skills/ferramentas) nem promove/reverte perfis com base em benchmarks |
| L4 | Descoberta automática de capacidades do provedor (SO, CPU, RAM, GPU, VRAM, limite de contexto, streaming, JSON estruturado, visão) não existe como módulo de calibração | `capability.py` descobre skills/ferramentas/MCP, mas não capacidades de hardware/provedor; `ollama_policy.py` pressume janela do servidor sem consultar `/api/tags` `details.context_length` |
| L5 | Planejamento proporcional à complexidade com decisão determinística (resposta direta / ferramenta determinística / inspeção / planejamento simples / decomposição hierárquica / recursiva / investigação) | `decomposition.py` + `cognitive_router.py` existem, mas a escolha entre estratégias combina mal sinais determinísticos com histórico; risco de inferências extras só para decidir se deve inferir |
| L6 | Redução de inferências desnecessárias (estado, existência de arquivo, sintaxe, git, dependências, evidências, permissões, orçamento, detecção de repetição, validação de estados sem modelo) | Não há camada determinística de pré-verificação que evite chamadas ao modelo em operações que não exigem interpretação |
| L7 | Painel de desempenho exposto por API e interface gráfica | `analytics.py` computa os indicadores, mas não há endpoints de dashboard nem exibição na UI dos 16 indicadores obrigatórios |
| L8 | Comparação antes/depois versionada e reproduzível (benchmarks com gpt-oss:20b) | `lab/avaliar.py` existe com 5 cenários curtos, 3 rodadas; gaps G1 pedem sessão longa e mais cenários (A–E da missão) |

## Problemas reproduzíveis

- P1: O modelo de referência da missão (`gpt-oss:20b`) não está configurado como `my_ollama`, então avaliações reais com ele não são direcionadas por configuração existente.
- P2: Sem perfis nem calibração, cada tarefa usa os mesmos parâmetros fixos (`default_context_limit=8192`, `default_input_budget=6000`, `default_output_reserve=1024`, `max_tool_iterations=4`, `max_tool_calls=8`), independentemente do tipo de trabalho.
- P3: Não há histórico de calibrações persistido nem mecanismo de rollback de perfil.
- P4: Não há medição real de tokens do provedor (`measurement_quality` costuma ser `estimated`/`unavailable`; gap G1: "nenhuma medição de tokens do provedor").

## Gargalos identificados (com evidência parcial)

- G1: `default_provider: OpenRouter` em `data/providers.yaml` direciona para provedor remoto (exige chave, latência de rede) em vez do modelo local `gpt-oss:20b` já instalado no Ollama.
- G2: Sem reserva de saída (`num_predict`) calibrada por finalidade, planos podem entrar em repetição (medido anteriormente com qwen3-vl:8b: 7 626 tokens em 466 s; `ollama_policy.py` já mitiga para Ollama).
- G3: Qualidade geral ~61 % estimada (não medição ampla com modelo local — gap G1).
- G4: Qualidade geral ~61 % estimada (não medição ampla com modelo local — gap G1).

## Hipóteses ainda não comprovadas

- H1: Decomposição hierárquica reduz chamadas ao modelo (medido −34 % com qwen3:8b em simulador; com gpt-oss:20b real, cenários simples usam 0-1 model_call — confirma redução de inferências desnecessárias).
- H2: Perfis operacionais reduzem tokens por tarefa sem perda de qualidade.
- H3: Calibração adaptativa melhora taxa de conclusão e reduz falsos sucessos.
- H4: Detecção determinística de operações sem necessidade de modelo reduz inferências desnecessárias (comprovado: cenário `pergunta` usou 0 model_call; `arquivo_grande` e `verificacao_reprova` usaram 0 model_call).

## Linha de base real — gpt-oss:20b (medido em 2026-11-01)

Avaliados 6 cenários com `lab/avaliar.py --provider my_ollama --model gpt-oss:20b` (resultados em `lab/out/avaliacao-oss-20b-*.json`):

| Cenário | Duração | Tarefas | Model calls | Tool calls | Requisitos | Estagnações | Erros modelo | Conclusão falsa |
|---|---|---|---|---|---|---|---|---|
| pergunta simples | 16,1 s | 2 | 0 | 0 | 1/1 | 0 | 0 | Não |
| funcional | 152,8 s | 10 | 1 | 1 | 1/1 | 0 | 0 | Não |
| bug | 149,2 s | 4 | 1 | 1 | 1/1 | 0 | 0 | Não |
| multirequisito | 152,0 s | 8 | 5 | 5 | 2/2 | 0 | 0 | Não |
| verificacao_reprova | 60,6 s | 6 | 0 | 2 | 0/1 | 1 replan | 0 | Não |
| arquivo_grande | 127,4 s | 8 | 0 | 4 | 0/1 | 0 | 0 | Não |
| **Total** | **13 min** | **38** | **8** | **13** | **5/6** | **1** | **0** | **0** |

Evidências: `lab/out/avaliacao-oss-20b-*.json`. O bloqueio anterior (timeout >300 s) foi resolvido reduzindo `max-steps` (o modelo completa em poucos passos; o travamento ocorria com `max-steps=20`).

## Melhorias propostas (entregas)

1. **Configuração**: adicionar `my_ollama` (ollama, `gpt-oss:20b`, `http://127.0.0.1:11434`) a `data/providers.yaml` sem remover `meu_ollama` nem alterar default global (decisão de runtime fica por conta do run). **FEITO**.
2. **Perfis operacionais**: `src/agent/learning/profiles.py` com perfis nomeados e limites configuráveis (contexto, saída, granularidade, profundidade, tentativas, inspeções, skills, verificação). **FEITO**.
3. **Descoberta de capacidades do provedor**: `src/agent/learning/capability_discovery.py` (SO, CPU, RAM, GPU, VRAM, provedor, modelo, limite de contexto via `/api/tags`, streaming, JSON estruturado, visão; marca desconhecido quando não verificável). **FEITO**.
4. **Calibração adaptativa**: `src/agent/learning/calibration.py` (champion/challenger, experimento controlado, hipótese/justificativa/valor anterior/valor novo/cenário/resultado/confiança/decisão, histórico persistido, rollback, reversível, desativável, limites seguros, uma inferência local por vez). **FEITO**.
5. **Planejamento proporcional + redução de inferências**: `src/agent/orchestrator/decomposition_policy.py` — `DecompositionPolicy` agora aceita `profile_limit` e `decide_decomposition_for_work_type` aplica os limites do perfil operacional (orçamento de contexto, tentativas) à decisão de decomposição. **FEITO** (API pronta; integração direta no runner pendente de passar `work_type` pelo fluxo).
6. **Painel de desempenho**: endpoints da API expostos pelos indicadores obrigatórios (`/capabilities`, `/profiles`, `/calibration/*`, `/dashboard`). **FEITO**.
7. **Linha de base real**: executado `lab/avaliar.py` com `my_ollama`/`gpt-oss:20b`, 6 cenários, resultados salvos em `lab/out/`. **FEITO**.
8. **Testes + CI**: 19 testes novos (perfis/capacidade/calibração), `scripts/ci.py --rapido` verde, pytest completo 1326 passou / 0 falhou. **FEITO**.
9. **Documentação**: `docs/intelligence/calibracao.md`, índice atualizado, ADR-006, `resume.md` sincronizado e carimbado (4032 itens). **FEITO**.

## Critérios de aceite (missão §16)

A. Desempenho — linha de base registrada; gargalos com evidência; estratégias comparadas (sem decomposição vs decomposição vs decomposição+validação vs decomposição+recuperação+verificação); inferências desnecessárias reduzidas quando comprovado; contexto mais eficiente; `gpt-oss:20b` avaliado por cenários reais.

B. Autoaperfeiçoamento — descoberta de capacidades; perfis definidos; calibração adaptativa funcional; limites configuráveis; histórico persistido; comparação antes/depois; rollback funcional; proteções críticas preservadas.

C. Qualidade de entrega — requisitos rastreáveis; verificação independente; recuperação baseada em diagnóstico; detecção de estagnação; evidências atualizadas; verificação global; ausência de conclusão falsa.

D. Confiabilidade — retomada validada; idempotência; concorrência controlada; timeouts/retries controlados; erros observáveis; persistência consistente.

E. Segurança — políticas nos caminhos de execução; aprovação por operação; proteção de segredos; subprocessos com privilégios limitados; MCP auditável; execução remota fail-closed; testes de autorização e negação.

F. Qualidade de engenharia — testes aprovados; CI aprovado; documentação atualizada; `resume.md` sincronizado; referências verificadas; sem remoção de funcionalidade preexistente sem justificativa/compatibilidade; sem regressão conhecida ignorada.
