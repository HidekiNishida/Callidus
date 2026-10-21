# Limitações conhecidas (v0.5)

O que o Callidus ainda não faz — e por quê.

1. **Decomposição LLM** — depende de Ollama reachable; fallback template genérico pode ser grosso em repos grandes.
2. **Visão** — referências preparadas; envio multimodal ao provedor requer perfil `supports_vision`.
3. **Concorrência** — uma inferência ativa por vez no executor compartilhado (`MAX_CONCURRENT_INFERENCES=1`), garantida para todas as sessões e threads do **processo**. **Dois processos** inferem em paralelo (medido): serializar exigiria trava externa, não justificada na instalação local. Ferramentas externas (compilador, testes, terminal) têm ciclo de vida próprio e podem rodar fora desse limite.
4. **Streaming de tokens** — não exposto na UI.
5. **MCP** — servidores pesados (npm) podem falhar por timeout; ajuste comando/cwd.
6. **Aprovações** — flag `approve_risky_tools` no run; UI granular pendente.
7. **Grafo** — indexação Python-first; relações `imports`/`calls` ainda heurísticas.
8. **Atomização** — micro-plano determinístico; decomposição LLM profunda ainda limitada.
9. **Contratos** — validação manual via `requires_contract`; propagação de impacto incompleta.
10. **Skills** — ativação lexical por palavra-chave; pedido muito indireto pode não ativar a skill ideal. O catálogo é relido do disco a cada `reload()`.
11. **Estratégia** — classifica por domínios fixos (consulta, QA, bug, refatoração, documentação, engenharia); pedidos híbridos ficam no domínio mais próximo.
12. **Recuperação da verificação** — reexecuta o mesmo verificador; não há estratégia de verificação alternativa nem leitura semântica da causa.
13. **Provedores** — a compatibilidade com OpenAI cobre `chat/completions`, `models`, streaming SSE, `tools` e `response_format`; não há `embeddings`, `audio` nem API em lote. As chamadas de ferramenta chegam na resposta (`tool_calls`) e o ciclo de ferramentas do agente existe para os provedores com `tool_loop` (Ollama, OpenAI-compatível, llama.cpp): Anthropic e Gemini seguem no protocolo JSON de uma tacada. Detalhes: [ciclo-ferramentas.md](/docs/architecture/ciclo-ferramentas.md). Anthropic não tem JSON estruturado nativo. Detalhes: [provedores.md](/docs/architecture/provedores.md).

16. **Ciclo de ferramentas** — o modelo pode inspecionar o projeto antes de responder, com orçamento de leituras (`max_tool_iterations`). Provedores sem `tool_loop` não entram no ciclo. A verificação implícita de uma escrita pelo modelo prova que o arquivo foi gravado, não que o pedido foi atendido: quem atesta o atendimento é o aceite global por requisito.

Detalhes: [skills-estrategia.md](/docs/architecture/skills-estrategia.md) · [ciclo-ferramentas.md](/docs/architecture/ciclo-ferramentas.md).

17. **Hierarquia de agentes** — a consulta entre agentes usa busca lexical entre
    pergunta e descoberta persistida (medição: 13/15, **0 falsos positivos**); perguntas
    realmente indiretas caem no caminho de inferência. Não há roteamento por grafo nem
    broker: a estratégia é *dirigida* (consulta o alvo e desce pela descendência).
    Descartar um agente não descarta a descendência em cascata — cada um é verificado
    individualmente, para não apagar resultado necessário. Nenhum backend oferece
    descarregamento do modelo ou retomada de inferência: o que se libera é o contexto
    de execução, não os pesos. A verificação de lastro da resposta do modelo também é
    lexical — uma síntese sem vocábulo em comum com o estado é marcada como sem lastro.
    Detalhes: [hierarquia-agentes.md](/docs/architecture/hierarquia-agentes.md).

Testes: `pytest` (41+ casos) · E2E mock: `tests/test_e2e_orchestrator.py` · recuperação: `tests/test_orchestrator_recovery.py`.

Backup: [scripts/backup-data.sh](/scripts/backup-data.sh).

Voltar: [architecture/README.md](/docs/architecture/README.md)

14. **Diagnóstico de provedor** — `GET /providers/{nome}/health` e `POST /providers/{nome}/test`
    respondem sempre com `ok: true/false` e o motivo; nunca estouram erro 500. A lista de modelos
    (`GET /providers/{nome}/models`) devolve 503 quando o servidor não responde.
18. **Automação de desktop** — os adaptadores de macOS, Windows e Linux estão no código.
    Nesta máquina (macOS) a geometria da tela foi lida; a captura parou em Screen Recording
    e a árvore de acessibilidade parou no erro `-10000` do System Events, com a instrução
    de permissão. Windows e Linux não foram executados. Wayland não recebe as mesmas
    capacidades do X11. Detalhes: [automacao-sistema.md](/docs/architecture/automacao-sistema.md).

19. **Qualidade e feed** — o contrato de qualidade é determinístico (perfis fixos, sem modelo).
    A disposição nova só troca o atomizador; o primeiro plano da raiz continua no planejador
    já existente. Não houve medição comparativa com o modelo local. A explicação do feed não
    declara critério verificado: o estado inicial é `pendente`.
    Detalhes: [orquestracao-qualidade.md](/docs/architecture/orquestracao-qualidade.md).

15. **Remoção em cascata** — a remoção de projeto e de conversa segue o grafo de chaves estrangeiras
    do modelo (`src/agent/services/cascade.py`); se alguma linha pendurada escapar, a API responde
    409 com o motivo em vez de 500.