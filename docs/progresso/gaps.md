# Gaps — a fila de trabalho

Tudo o que falta no Callidus, ranqueado pelo quanto bloqueia quem o usa para desenvolver com modelos locais pequenos.

Voltar: [docs/progresso/](/docs/progresso/README.md) · Formato: [progresso.md](/docs/regras/progresso.md)

> **Revisado em:** 2026-11-04 · **Atualizado em:** 2026-11-04 · **Mudança:** minor (G16 aberto; G7 atualizado)

É a fila de trabalho: sem tarefa dada, pegue o **maior rank em que consiga avançar** e atualize a entrada na mesma entrega. Os ids (`G1`, `G2`…) são estáveis; o rank muda. As fontes desta primeira versão são [limitacoes.md](/docs/architecture/limitacoes.md), [diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md), a [avaliação reproduzível](/docs/architecture/avaliacao.md) e a auditoria de 2026-10-21 (`.cursor/CALLIDUS_AUDITORIA.md`, `.cursor/CALLIDUS_DESCOBERTAS.md`). Todas as horas são *estimadas*.

## 📋 Fila

| Rank | Gap | Horas | Bloqueia o beta? | Checklist |
|------|-----|-------|------------------|-----------|
| 1 | [G1 Avaliação real ampla e repetível](#g1-avaliação-real-ampla-e-repetível) | 10 | Sim | [desempenho](/docs/progresso/checklists/desempenho.md) |
| 2 | [G2 Decomposição em repositórios grandes](#g2-decomposição-em-repositórios-grandes) | 16 | Sim | [funcionalidades](/docs/progresso/checklists/funcionalidades.md) |
| 3 | [G16 Fidelidade do artefato e verificação da entrega](#g16-fidelidade-do-artefato-e-verificação-da-entrega) | 8 | Não | [qualidade](/docs/progresso/checklists/qualidade.md) |
| 4 | [G3 Recuperação quando a verificação reprova](#g3-recuperação-quando-a-verificação-reprova) | 3 | Sim | [funcionalidades](/docs/progresso/checklists/funcionalidades.md) |
| 5 | [G4 Aprovação granular de ferramentas arriscadas na UI](#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui) | 4 | Sim | [segurança](/docs/progresso/checklists/seguranca.md) |
| 6 | [G5 Defeitos conhecidos do feed](#g5-defeitos-conhecidos-do-feed) | 5 | Não | [interface](/docs/progresso/checklists/interface.md) |
| 7 | [G6 Fiscais automáticos das regras de engenharia](#g6-fiscais-automáticos-das-regras-de-engenharia) | 6 | Não | [qualidade](/docs/progresso/checklists/qualidade.md) |
| 8 | [G7 Seleção lexical de skills, estratégia e consulta](#g7-seleção-lexical-de-skills-estratégia-e-consulta) | 12 | Não | [funcionalidades](/docs/progresso/checklists/funcionalidades.md) |
| 9 | [G8 Grafo de conhecimento multi-linguagem](#g8-grafo-de-conhecimento-multi-linguagem) | 14 | Não | [funcionalidades](/docs/progresso/checklists/funcionalidades.md) |
| 10 | [G9 Propagação de impacto de contratos](#g9-propagação-de-impacto-de-contratos) | 8 | Não | [funcionalidades](/docs/progresso/checklists/funcionalidades.md) |
| 11 | [G10 Streaming de tokens na interface](#g10-streaming-de-tokens-na-interface) | 2 | Não | [interface](/docs/progresso/checklists/interface.md) |
| 12 | [G11 Paridade entre provedores](#g11-paridade-entre-provedores) | 10 | Não | [plataformas](/docs/progresso/checklists/plataformas.md) |
| 13 | [G12 Automação de desktop nas três plataformas](#g12-automação-de-desktop-nas-três-plataformas) | 10 | Não | [plataformas](/docs/progresso/checklists/plataformas.md) |
| 14 | [G13 Versão e licença](#g13-versão-e-licença) | 1 | Sim | [qualidade](/docs/progresso/checklists/qualidade.md) |
| 15 | [G14 Documentação de limitações desatualizada](#g14-documentação-de-limitações-desatualizada) | 1 | Não | [qualidade](/docs/progresso/checklists/qualidade.md) |
| 16 | [G15 Servidores MCP pesados](#g15-servidores-mcp-pesados) | 3 | Não | [plataformas](/docs/progresso/checklists/plataformas.md) |

**Total estimado:** 113 h · **Bloqueiam o beta:** G1, G2, G3, G4, G13 (34 h).

Fora de escopo por decisão registrada: serializar inferência entre **processos** ([limitacoes.md](/docs/architecture/limitacoes.md), item 3).

## G1 Avaliação real ampla e repetível

- **Faltando:** só 5 cenários curtos, 3 rodadas por lado ([avaliacao.md](/docs/architecture/avaliacao.md)); nenhuma sessão longa de produção; cenários B–F da auditoria só parciais; a disposição de qualidade nunca foi comparada com o modelo local ([limitacoes.md](/docs/architecture/limitacoes.md), item 19); nenhum benchmark multilíngue; sem medição de tokens do provedor.
- **Feito:** `lab/avaliar.py` com aceite objetivo e falha injetada; 15/15 cenários aceitos em 2026-10-20 com `gpt-oss:20b` (*medido*). `scripts/simular-qwen3.py`: fluxo inteiro contra um servidor Ollama simulado — com a janela padrão de 4 096, dois cenários com arquivo de tamanho comum passaram de pausados (20 chamadas, 18 com o prompt cortado) a concluídos (6–7 chamadas, nenhum corte) (*medido*, 2026-10-22, [avaliacao.md](/docs/architecture/avaliacao.md#-qwen38b--servidor-ollama-simulado)).
- **Faltando (qwen3:8b):** a avaliação real com `qwen3:8b` (`lab/avaliar.py --model qwen3:8b`, três rodadas por lado); a amostragem por finalidade do qwen3 é padrão do fabricante + julgamento, ainda sem medição.

## G2 Decomposição em repositórios grandes

- **Faltando:** a decomposição por modelo depende do Ollama acessível; o modelo de reserva é genérico e grosso em repositório grande; a atomização profunda por modelo ainda é limitada ([limitacoes.md](/docs/architecture/limitacoes.md), itens 1 e 8); falta o comparativo A/B decomposição × contexto monolítico ([diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md)).
- **Feito:** micro-plano determinístico, decomposição hierárquica com testes (`tests/test_hierarchical_decompose.py`, `tests/test_decomposition.py`).

## G3 Recuperação quando a verificação reprova

- **Faltando:** leitura semântica da causa pelo modelo (o diagnóstico é por padrões da saída); medir com o modelo real quantas reprovações a recuperação converte em aprovação.
- **Feito:** portão único (`VerificationGate` é fachada de `finalize_verification`); reprovação registra o critério não satisfeito, o diagnóstico e um complemento somente-leitura que estreita a causa — sem nunca aprovar por um verificador mais fraco (o verde falso do gate antigo foi removido); escrita reprovada é desfeita e a orientação chega à nova tentativa (`tests/test_etapas_cenarios.py::test_cenario2_*`, `tests/test_verification_gate.py`). Estagnação, replanejamento, pausa e retomada (`tests/test_orchestrator_recovery.py`, `tests/test_stagnation_limits.py`).

## G4 Aprovação granular de ferramentas arriscadas na UI

- **Faltando:** a interface ainda não lista os pedidos nem oferece aprovar/negar ([limitacoes.md](/docs/architecture/limitacoes.md), item 6).
- **Feito:** backend completo — pedido persistido por operação (`tool_approvals`), avaliado na hora da execução, uso único, negação, pausa do run e retomada pela decisão, rotas `GET /runs/{id}/approvals` e `POST /approvals/{id}/approve|deny`, retomada sem repetir operação não repetível após queda (`tests/test_granular_approval.py`). Política por pedido (`src/agent/tools/policy.py`, `tests/test_request_permissions.py`).

## G5 Defeitos conhecidos do feed

- **Faltando:** duplicata visual entre `agent.thought` e `work.explained`; com várias runs na mesma mensagem raiz só a mais recente é reidratada; a narração cai na última linha operacional por falta de `correlation_id` no backend (auditoria de 2026-10-21).
- **Feito:** narração dentro do item, histórico reidratado ao reabrir conversa, regressão com fixture real (`tests/web/narrative-replay.test.mjs`).

## G6 Fiscais automáticos das regras de engenharia

- **Faltando:** proteção de branch exigindo o check do CI (decisão do dono); um fiscal geral de camadas (o teste de importação cobre só `domain/organization.py` e `domain/work_flow.py`); nenhum fiscal garante testes sem rede; `scripts/padronizar_cabecalhos.py --check` sai com 0 mesmo quando falta cabeçalho.
- **Feito:** comando único `python scripts/ci.py` agregando lint, cabeçalhos, documentação, `resume.md`, interface e suíte Python; caminhos absolutos do Mac trocados por caminhos do repositório em `internal/tarefas/`, para a verificação de referências passar em qualquer máquina (2026-10-21). CI remoto em `.github/workflows/ci.yml` rodando `scripts/ci.py` com permissão só de leitura, `ruff` no grupo `[dev]`, checagem de sintaxe e importações da SPA no comando único (2026-11-03).

## G7 Seleção lexical de skills, estratégia e consulta

- **Faltando:** skills ativadas por palavra-chave; estratégia por domínios fixos; consulta entre agentes por busca lexical (13/15, 0 falsos positivos — *medido*); verificação de lastro também lexical ([limitacoes.md](/docs/architecture/limitacoes.md), itens 10, 11 e 17).
- **Feito:** catálogo de skills recarregável e medição de consulta (`scripts/medir-hierarquia.py`). Papel e especialidades gravados em `metadata_json["assignment"]`; `QueryService` agora ordena descendentes por correspondência entre pergunta e especialidade, mantendo o alvo explícito e exigindo evidência pertinente (teste determinístico em `tests/test_query_service.py`, 2026-11-04).

## G8 Grafo de conhecimento multi-linguagem

- **Faltando:** indexação Python-first; relações `imports`/`calls` heurísticas; sem UI gráfica do grafo nem diff de contexto por snapshot ([limitacoes.md](/docs/architecture/limitacoes.md), item 7; [diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md)).
- **Feito:** grafo com testes (`tests/test_knowledge_graph.py`, `tests/test_knowledge_imports.py`).

## G9 Propagação de impacto de contratos

- **Faltando:** validação manual via `requires_contract`; propagação de impacto incompleta ([limitacoes.md](/docs/architecture/limitacoes.md), item 9).
- **Feito:** serviço e impacto de contratos com testes (`tests/test_contract_service.py`, `tests/test_contract_impact.py`).

## G10 Streaming de tokens na interface

- **Faltando:** narração com o `gpt-oss:20b` (o Ollama devolve o preâmbulo só no canal de raciocínio); checkpoint do texto parcial quando o processo morre no meio da geração.
- **Feito:** streaming SSE de eventos da run (`/runs/{id}/stream`). Narração do agente em tempo real ([narracao-tempo-real.md](/docs/architecture/narracao-tempo-real.md)): eventos `agent.narration.*` filtrados dos mesmos fragmentos (sem inferência extra), linha própria na Atividade do agente, reconexão sem duplicar, histórico ao recarregar; com `qwen3-vl:8b` real, primeiro trecho visível a 355 ms (*medido*, `lab/medir_narracao.py`); `tests/test_narration_stream.py`, `tests/web/live-narration.test.mjs`. Avaliação antes/depois com `gpt-oss:20b`: sem regressão, 6/6 aceitos depois (*medido*, uma rodada por lado, [avaliacao.md](/docs/architecture/avaliacao.md#-narração-em-tempo-real--antes-e-depois-02112026-gpt-oss20b)).

## G11 Paridade entre provedores

- **Faltando:** Anthropic e Gemini fora do ciclo de ferramentas (`tool_loop`); Anthropic sem JSON estruturado nativo; sem `embeddings`, `audio` nem lote no modo OpenAI-compatível; visão só com `supports_vision` ([limitacoes.md](/docs/architecture/limitacoes.md), itens 2 e 13).
- **Faltando (janela):** o llama.cpp e o OpenAI-compatível não recebem a política de janela e saída do Ollama — no llama.cpp a janela é a do `--ctx-size` do servidor, que o Callidus não confere.
- **Feito:** Ollama, OpenAI-compatível, llama.cpp, OpenRouter, Anthropic e Gemini com testes de provedor. Streams de OpenAI-compatível, llama.cpp, Anthropic e Gemini passaram a remontar as chamadas de ferramenta (antes descartadas com streaming ligado) e a separar o raciocínio (`tests/test_narration_stream.py`). Ollama com política por família (`ollama_policy.py`): `num_ctx`/`num_predict` explícitos, amostragem do `qwen3` por finalidade, `<think>` e `<tool_call>` no texto corrigidos (`tests/test_qwen3_ollama_policy.py`).

## G12 Automação de desktop nas três plataformas

- **Faltando:** no macOS a captura parou em Screen Recording e a acessibilidade no erro `-10000`; Windows e Linux nunca executados; Wayland sem as capacidades do X11 ([limitacoes.md](/docs/architecture/limitacoes.md), item 18).
- **Feito:** adaptadores das três plataformas com testes (`tests/test_desktop_automation.py`, `tests/test_desktop_accessibility.py`).

## G13 Versão e licença

- **Faltando:** `pyproject.toml` declara `0.1.0` e a documentação fala em v0.5; não há `LICENSE` na raiz, embora o selo do [README](/README.md) diga MIT e aponte para ele. A licença é **decisão do dono**.

## G14 Documentação de limitações desatualizada

- **Faltando:** [limitacoes.md](/docs/architecture/limitacoes.md) tem a numeração fora de ordem (… 13, 16, 17, 14, 18, 19, 15) e diz "41+ casos" de teste, quando há 847 funções `test_` (*medido*).

## G15 Servidores MCP pesados

- **Faltando:** servidores MCP via npm podem estourar o timeout; o ajuste de comando/cwd é manual ([limitacoes.md](/docs/architecture/limitacoes.md), item 5).

## G16 Fidelidade do artefato e verificação da entrega

- **Faltando:** verificadores específicos para documentos, planilhas, pesquisas e interfaces ainda não são uma etapa obrigatória comum; um projeto web pode passar por critério textual sem abrir no navegador nem exercitar controles; ainda não há um gate final universal que confira requisito → artefato → evidência recente.
- **Feito nesta entrega:** tarefas que nomeiam explicitamente um arquivo são reprovadas quando evidência de `file_contains`, `file_exists` ou sintaxe aponta para outro arquivo (`tests/test_global_acceptance.py`); o contrato de qualidade reconhece pedidos de site em português e exige estrutura, responsividade, controles funcionais, feedback e recursos visuais utilizáveis (`tests/test_quality_disposition.py`); a aba Organização mostra o handoff persistido e consultas descendentes priorizam especialidades (57 testes Python focados e 3 testes web passaram, 2026-11-04). O caso «site de culinária» foi refeito e exercitado no navegador em desktop e mobile; veja o checklist da tarefa para as evidências.
- **Estimativa:** 8 h; não altera o portão ou os critérios de estágio.

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-11-04 | minor | G16 aberto; evidência de arquivo divergente rejeitada, critérios de site ampliados, handoff na UI e roteamento por especialidade concluídos |
| 2026-11-02 | minor | G10: narração do agente em tempo real (horas de 5 para 2); G11: ferramentas e raciocínio nos streams de quatro provedores |
| 2026-10-22 | minor | Adaptação ao `qwen3:8b`: janela e saída explícitas no Ollama, estimativa calibrada, conversa do ciclo na janela, reparo do plano; G1 com a medição simulada e a real pendente; G11 com a política por família |
| 2026-10-21 | major | Criação: 15 gaps tirados das limitações, do diagnóstico, da avaliação e da auditoria |
