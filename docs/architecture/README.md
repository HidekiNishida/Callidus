# Arquitetura do runtime

![Projeto](/media/icons/projeto.svg){width=48}

Hub técnico do **Callidus** (código em [/src/agent/](/src/agent/README.md)).

## Documentos

| Doc | Tema |
|-----|------|
| [visao-geral.md](/docs/architecture/visao-geral.md) | Módulos e fases |
| [modelo-dados.md](/docs/architecture/modelo-dados.md) | SQLite |
| [maquina-estados.md](/docs/architecture/maquina-estados.md) | Tarefas |
| [execucao-local.md](/docs/architecture/execucao-local.md) | Instalação, **Ollama padrão** |
| [provedores.md](/docs/architecture/provedores.md) | **Provedores** — Ollama, llama.cpp, OpenRouter, OpenAI-compatível, Anthropic, Gemini, mock |
| [execucao-remota.md](/docs/architecture/execucao-remota.md) | **Computador remoto** — projeto em servidor Linux/macOS/Windows por SSH |
| [ferramentas.md](/docs/architecture/ferramentas.md) | Tools |
| [ciclo-ferramentas.md](/docs/architecture/ciclo-ferramentas.md) | **Ciclo de ferramentas da operação** — inspeção com ferramentas antes de responder |
| [mcp.md](/docs/architecture/mcp.md) | MCP stdio |
| [frontend.md](/docs/architecture/frontend.md) | UI |
| [ux-ui.md](/docs/architecture/ux-ui.md) | Análise UX + layout |
| [limitacoes.md](/docs/architecture/limitacoes.md) | Gaps conhecidos |
| [diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md) | Evolução v0.5 |
| [knowledge-graph.md](/docs/architecture/knowledge-graph.md) | Grafo do projeto |
| [context-builder.md](/docs/architecture/context-builder.md) | Contexto por operação |
| [execucao-autonoma.md](/docs/architecture/execucao-autonoma.md) | Worker autônomo |
| [requisitos-verificacao-progresso.md](/docs/architecture/requisitos-verificacao-progresso.md) | Requisitos rastreáveis, validação do plano, verificação independente, progresso real |
| [avaliacao.md](/docs/architecture/avaliacao.md) | **Avaliação reproduzível** — cenários com critérios objetivos e resultado medido com o modelo local |
| [skills-estrategia.md](/docs/architecture/skills-estrategia.md) | Skills sob demanda, estratégia profissional, decomposição recursiva e recuperação da verificação |
| [hierarquia-agentes.md](/docs/architecture/hierarquia-agentes.md) | **Hierarquia de agentes** — executor compartilhado, ciclo de vida, consultas sob demanda, escalonador e descarte |

Voltar: [docs/README.md](/docs/README.md) · [README raiz](/README.md)
