# Documentação (`docs/`) — Índice geral

O índice geral da documentação: onde está cada assunto e quando consultá-lo.

Índice de nível 1: **onde está cada assunto** e **quando consultar**. A estratégia é de
divulgação progressiva — comece por [`../README.md`](../README.md), siga o link do assunto e
desça até o detalhe. Quem procura uma funcionalidade em código deve usar os
[READMEs de módulo](/src/agent/README.md) e o [mapa de módulos](/docs/architecture/visao-geral.md).

## 🗺️ Como escolher por onde começar

| Se você quer… | Comece por |
|---------------|-----------|
| Rodar o Callidus | [README raiz](/README.md) · [execucao-local.md](/docs/architecture/execucao-local.md) |
| Entender a arquitetura | [visao-geral.md](/docs/architecture/visao-geral.md) · [src/agent/README.md](/src/agent/README.md) |
| Mudar código com segurança | [AGENTS.md](/AGENTS.md) · [regras/](/docs/regras/README.md) |
| Onde está uma funcionalidade | [mapa de módulos](/docs/architecture/visao-geral.md) · [src/agent/README.md](/src/agent/README.md) |
| Entender o estado persistido | [modelo-dados.md](/docs/architecture/modelo-dados.md) · [maquina-estados.md](/docs/architecture/maquina-estados.md) |
| Integrar um provedor de modelo | [provedores.md](/docs/architecture/provedores.md) · [providers/README.md](/src/agent/providers/README.md) |
| Integrar uma ferramenta | [ferramentas.md](/docs/architecture/ferramentas.md) · [tools/README.md](/src/agent/tools/README.md) |
| Entender a verificação | [requisitos-verificacao-progresso.md](/docs/architecture/requisitos-verificacao-progresso.md) · [verification/README.md](/src/agent/verification/README.md) |
| Trabalhar na interface | [frontend.md](/docs/architecture/frontend.md) · [api/README.md](/src/agent/api/README.md) |
| Escrever ou ajustar testes | [validacoes-testes.md](/docs/regras/validacoes-testes.md) · [tests/](/tests) |

## 🏗️ Arquitetura e runtime

| Documento | Assunto | Quando consultar |
|-----------|---------|------------------|
| [architecture/visao-geral.md](/docs/architecture/visao-geral.md) | Módulos, camadas e o caminho de um pedido | Antes de mexer em qualquer módulo |
| [architecture/modelo-dados.md](/docs/architecture/modelo-dados.md) | Tabelas, migrações e integridade | Ao criar coluna ou tabela |
| [architecture/maquina-estados.md](/docs/architecture/maquina-estados.md) | Estados e transições de tarefa/run/agente | Ao mudar um status ou uma regra de ciclo |
| [architecture/requisitos-verificacao-progresso.md](/docs/architecture/requisitos-verificacao-progresso.md) | Requisitos, validação do plano, verificação independente, progresso | Ao mexer em critério de aceite ou evidência |
| [architecture/execucao-local.md](/docs/architecture/execucao-local.md) | Instalação e execução local (Ollama por padrão) | Ao configurar o ambiente |
| [architecture/execucao-remota.md](/docs/architecture/execucao-remota.md) | Projeto em servidor remoto por SSH | Ao operar o agente em outra máquina |
| [architecture/execucao-autonoma.md](/docs/architecture/execucao-autonoma.md) | Worker autônomo e escalonador | Ao mexer no laço em background |
| [architecture/provedores.md](/docs/architecture/provedores.md) | Ollama, llama.cpp, OpenRouter, OpenAI-compatível, Anthropic, Gemini, mock | Ao adicionar ou trocar provedor |
| [architecture/ferramentas.md](/docs/architecture/ferramentas.md) | Registro, execução e permissões das ferramentas | Ao criar ou ajustar uma ferramenta |
| [architecture/automacao-sistema.md](/docs/architecture/automacao-sistema.md) | Sistema, desktop, engenharia, navegador e skills autorais | Ao automatizar o computador ou criar uma skill |
| [architecture/ciclo-ferramentas.md](/docs/architecture/ciclo-ferramentas.md) | Inspeção com ferramentas antes da resposta | Ao mexer no protocolo da operação |
| [architecture/context-builder.md](/docs/architecture/context-builder.md) | Montagem e orçamento de contexto | Ao mexer no prompt ou no orçamento |
| [architecture/mcp.md](/docs/architecture/mcp.md) | MCP stdio | Ao integrar um servidor MCP |
| [architecture/knowledge-graph.md](/docs/architecture/knowledge-graph.md) | Grafo do projeto | Ao mexer no índice de código |
| [architecture/hierarquia-agentes.md](/docs/architecture/hierarquia-agentes.md) | Árvore de agentes, consultas e descarte | Ao mexer no executor compartilhado |
| [architecture/automacoes.md](/docs/architecture/automacoes.md) | Automações, gatilhos, ações e supervisor | Ao mexer em automação |
| [architecture/frontend.md](/docs/architecture/frontend.md) | SPA, streaming e estado da interface | Ao mexer no frontend |
| [architecture/ux-ui.md](/docs/architecture/ux-ui.md) | Análise de UX e layout | Ao redesenhar telas |
| [architecture/skills-estrategia.md](/docs/architecture/skills-estrategia.md) | Skills, estratégia profissional e decomposição recursiva | Ao mexer em skills ou decomposição |
| [architecture/orquestracao-qualidade.md](/docs/architecture/orquestracao-qualidade.md) | Contrato de qualidade, decomposição seletiva e feed | Ao mexer em planejamento ou no feed |
| [architecture/estrategia-linguistica.md](/docs/architecture/estrategia-linguistica.md) | Idioma do pedido, operação em inglês e idioma da interface | Ao mexer no prompt ou na língua da resposta |
| [architecture/avaliacao.md](/docs/architecture/avaliacao.md) | Avaliação reproduzível com critérios objetivos | Ao medir uma mudança de comportamento |
| [architecture/limitacoes.md](/docs/architecture/limitacoes.md) | Lacunas conhecidas | Antes de prometer algo que ainda não existe |
| [architecture/diagnostico-evolucao.md](/docs/architecture/diagnostico-evolucao.md) | Diagnóstico e plano de evolução | Ao planejar a próxima versão |

## 🗺️ Regras de trabalho

| Documento | Assunto | Quando consultar |
|-----------|---------|------------------|
| [AGENTS.md](/AGENTS.md) | **Fonte canônica** — cabeçalho, docstrings, SOLID, testes, documentação | Antes de escrever código |
| [regras/README.md](/docs/regras/README.md) | Hub das regras (paperback, escopo, processo) | Para saber qual regra se aplica |
| [regras/principios.md](/docs/regras/principios.md) | Princípios do produto e prioridades | Em decisões de tradeoff |
| [regras/documentacao.md](/docs/regras/documentacao.md) | Como documentar código e documentos | Ao escrever ou editar documentação |
| [regras/organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md) | Onde cada arquivo vive | Antes de criar ou mover arquivo |
| [regras/validacoes-testes.md](/docs/regras/validacoes-testes.md) | Estratégia e comandos de teste | Ao escrever teste ou verificar mudança |
| [regras/verificacao-final.md](/docs/regras/verificacao-final.md) | Checklist de entrega | Antes de fechar uma tarefa |
| [regras/resumo-projeto.md](/docs/regras/resumo-projeto.md) | Resumo do projeto | Para saber o que o Callidus é |
| [regras/navegacao-agentes.md](/docs/regras/navegacao-agentes.md) | Navegação entre agentes e papéis | Ao definir quem faz o quê |
| [regras/readmes-pastas.md](/docs/regras/readmes-pastas.md) | Regra do README por pasta | Ao criar uma pasta |

## 🧪 Verificação da própria documentação

As regras acima são verificáveis por máquina — a verificação é leve e reproduzível:

```bash
source .venv/bin/activate
python scripts/check_docs.py         # links e âncoras
python scripts/check_references.py   # arquivos e símbolos citados
python scripts/check_markdown.py     # estrutura dos documentos
```

Detalhes: [scripts/README.md](/scripts/README.md) · regra completa:
[regras/documentacao.md](/docs/regras/documentacao.md).

## 📚 Contexto e continuidade

| Documento | Assunto | Quando consultar |
|-----------|---------|------------------|
| [project-context.md](/docs/project-context.md) | Metas e restrições do projeto | Para saber o que o projeto prioriza |
| [../resume.md](/resume.md) | Mapa vivo de funções e behaviours (gerado por `scripts/resume.py`) | Para localizar uma função concreta |
| [../internal/tarefas/](/internal/tarefas/) | Checklists e estado das tarefas | Para retomar um trabalho |

Voltar: [README raiz](/README.md) · [Código](/src/agent/README.md)