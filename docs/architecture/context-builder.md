# Context Builder por operação

![configuracao](/media/icons/configuracao.svg){width=48}

A montagem do contexto e o orçamento de tokens.

Cada chamada ao modelo para uma tarefa passa por `OperationContextBuilder`, que monta mensagens mínimas e persiste um `ContextSnapshotModel`.

## 🔄 Entradas

- Memória canônica do projeto (até 5 registros recentes).
- Objetivo e critérios da tarefa.
- **Requisitos obrigatórios que a etapa cobre** (obrigatório): id, descrição e critério de aceite de cada requisito do qual esta etapa é responsável. Sem este bloco o modelo executava a etapa sem saber o que tinha de provar: o critério de aceite canônico não chegava ao prompt, e a validação depois apontava o requisito como não comprovado.
- **Arquivos-alvo** (obrigatório): conteúdo atual dos arquivos citados no título, objetivo, critérios, contrato ou `tool_args.path` que existem dentro do projeto — até 8 mil caracteres por arquivo e 12 mil no total; arquivo maior entra com o início e o aviso do tamanho. Nunca é compactado, para `old_string` casar com o disco. A lista vai em `strategy_notes_json` (`arquivos: …`).
- **Contrato** (obrigatório, se existir): entradas, saídas, invariantes e aceite do `TaskContractModel`.
- **Objetivo global** (obrigatório): objetivo da raiz, quando a tarefa é um passo dele.
- **Resultados das dependências** (opcional): título, status e resumo do resultado de cada tarefa da qual esta depende.
- **Tentativas anteriores** (obrigatório, se houver falhas): ver abaixo.
- Trechos técnicos (símbolos sugeridos pelo grafo).
- Guias do repositório na raiz: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, Copilot, `.cursor/rules`, `llms.txt`, índice de `SKILL.md`. Um `AGENTS.md` de subpasta entra só se o pedido cita essa pasta.
- Regras globais fixas e resumo de ferramentas autorizadas.

A resposta final usa os formatos que o chat desenha (título, lista, tabela, código, mermaid e fontes). Visão só entra se o id do modelo indica um modelo visual.

## ⚙️ Orçamento

`build_operation_context` aplica limite do `ModelProfile`, reserva de saída e margem de segurança (256 tokens). Regras globais, objetivo, **requisitos**, critérios, formato de saída, **objetivo global** e **regras do projeto** são **obrigatórios**; skills, contexto técnico e ferramentas entram se couberem, e os omitidos ficam em `refs_json` e `strategy_notes_json`.

O que é grande e dispensável (skills, contexto técnico, resumo de ferramentas) é o que sai quando falta espaço. O objetivo global e as regras do projeto são protegidos porque são o *porquê* da etapa e as restrições canônicas do projeto: perdê-los faz o modelo errar sem perceber.

### Nova tentativa

Quando a tarefa já falhou, o componente obrigatório `tentativas-anteriores` (`describe_failures`) traz as últimas 3 falhas: causa, detalhe (com o fim da saída da verificação, se for o caso) e o que fazer diferente (`retry_hint`). Assim cada tentativa recebe um pedido diferente da anterior.

O runner guarda a impressão do prompt (`request_json.prompt_fp`, que inclui os parâmetros de geração). Se o próximo pedido for idêntico a um já enviado, ele não é enviado: falha `change_strategy/repeated_prompt` e a tarefa vai a `BLOCKED`. Resposta cortada (`truncated_output`) dobra `num_predict` a cada ocorrência, até 16384.

### Quando o obrigatório não cabe

1. `assemble_messages` lança `ContextBudgetError` com o custo de cada componente.
2. O builder grava um snapshot do estouro (`strategy_notes_json` começa com `estouro:`).
3. O runner tenta de novo com `compact=True`: `compact_text` tira espaços repetidos, linhas em branco seguidas e linhas duplicadas, sem cortar conteúdo.
4. Se ainda não couber, nada é enviado ao modelo: a tentativa vira falha `change_strategy/context_budget`, a tarefa passa a `BLOCKED` com a explicação (parte maior, tokens, orçamento) e a ação é `blocked_context`. Conteúdo obrigatório nunca é truncado para caber.

## 🔄 Inspeção

- `GET /tasks/{id}/context-snapshots`
- `GET /context-snapshots/{id}`
- Aba **Contexto** na UI web.

Código: [operation_builder.py](/src/agent/context/operation_builder.py)