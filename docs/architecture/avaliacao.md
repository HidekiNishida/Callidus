# Avaliação reproduzível do Callidus

A avaliação reproduzível com critérios objetivos de aceite.

Ferramenta de medição: [`lab/avaliar.py`](/lab/avaliar.py). Executa um conjunto de cenários com o
**Ollama local** num banco e numa pasta de trabalho **isolados** — nada do banco, dos projetos ou
das credenciais do usuário é tocado. Cada cenário tem critérios de aceite **objetivos**, e o
resultado é medido (tarefas, chamadas, tokens, evidências, requisitos comprovados).

```bash
# estado atual
python lab/avaliar.py --label depois --max-steps 120

# estado de um commit (para comparar)
git stash push -- src && python lab/avaliar.py --label antes --max-steps 120 && git stash pop
```

Saída: `lab/out/avaliacao-<label>.json` (resumo + cenário a cenário) e um resumo no terminal.

## 🔄 Modo de execução

| Parâmetro | Padrão | Papel |
|-----------|--------|-------|
| `--label` | `atual` | nome do arquivo de saída |
| `--model` | `gpt-oss:20b` | modelo do Ollama local |
| `--provider` | `meu_ollama` | provedor configurado em `data/providers.yaml` |
| `--max-steps` | `40` | orçamento de passos por cenário |
| `--only` | — | roda só os cenários cujo nome casa |
| `--fault` | — | injeta uma falha determinística no provedor para medir a resposta do sistema à repetição improdutiva |

O provedor e o modelo vêm da **configuração**, não do código: o cenário monta o run com
`provider`/`model_id` e o Callidus resolve pelo catálogo de provedores. Nenhum serviço externo é
usado; se o Ollama não estiver disponível, a avaliação real não pode ser feita (e isso precisa
ser dito, não estimada).

### Falha injetada (`--fault`)

A avaliação com o modelo real mede o **caminho feliz**. Para medir a resposta do sistema à
repetição improdutiva, o `--fault` troca o provedor por um que reproduz uma falha observada em
produção, de forma determinística:

| Modo | Falha reproduzida | O que mede |
|------|-------------------|------------|
| `invalido` | o modelo devolve prosa em vez da entrega | a detecção de repetição e o replanejamento |
| `vazio` | o modelo raciocina e não entrega | o corte de saída e a ampliação de orçamento |
| `http400` | o provedor recusa o pedido (HTTP 400) | a diferença entre falha transitória e permanente |
| `transitorio` | a conexão cai **uma** vez e depois passa | a repetição legítima |

O provedor falso é **uma instância só** para o run inteiro — é o que permite que a falha
transitória falhe uma vez e deixe o agente passar. A métrica que interessa aqui não é o aceite do
cenário (que naturalmente reprova), e sim **quantas chamadas o sistema gastou antes de parar** e
**o que ele registrou como diagnóstico**.

Além do resumo de sempre, cada cenário passa a reportar `estagnacoes`, `replanejamentos`,
`pausas` e o `problem_ledger` da raiz (a contagem por problema).

## 🧪 Cenários e critérios de aceite

| Cenário | O que mede | Critérios |
|---------|-----------|-----------|
| `funcional` | tarefa simples com critério objetivo | `app.py` passa a conter `def dobro`; a suíte passa |
| `bug` | investigação de causa raiz | `add` passa a somar; a suíte passa |
| `arquivo_grande` | o mesmo bug num módulo de ~9 KB | `add` soma; a suíte passa; as outras 45 funções do módulo continuam lá (reescrita cortada apaga funções) |
| `multirequisito` | dois requisitos no mesmo pedido | `a.py` tem `soma` **e** `b.py` tem `sub`; os dois requisitos comprovados |
| `verificacao_reprova` | a verificação reprova e o pedido é só reportar | nenhum arquivo alterado; a resposta final **diz** que o teste reprovou |
| `pergunta_simples` | pergunta sem trabalho | nenhum arquivo criado (não há árvore de subtarefas) |

O `verificacao_reprova` é o cenário anti-conclusão-falsa: o pedido é "execute a suíte e diga o
resultado, não altere nenhum arquivo", a suíte do projeto está quebrada. O comportamento correto
é rodar, reportar a reprovação e **não** mexer no projeto.

## 🎯 Resultado medido (20/10/2026, `gpt-oss:20b` via Ollama local)

Mesmos cenários, mesmo modelo, mesmo ambiente; a diferença é só o código.

| Métrica | Antes | Depois | Δ |
|---------|-------|--------|---|
| Cenários com aceite integral | 3 / 5 | **5 / 5** | +2 |
| Runs que chegaram a um estado final | 5 / 5 | 5 / 5 | — |
| Requisitos obrigatórios comprovados | 4 / 6 | **6 / 6** | +2 |
| Conclusões prematuras | 0 | 0 | — |
| Tarefas criadas | 65 | **31** | −52 % |
| Chamadas ao modelo | 65 | **9** | −86 % |
| Falhas de modelo | 15 | **1** | −93 % |
| Tokens de completion | 19 333 | **6 099** | −68 % |
| Tempo total | 622 s | **183 s** | −71 % |

Por cenário (antes → depois):

| Cenário | Antes | Depois |
|---------|-------|--------|
| `funcional` | 13 tarefas, 19 chamadas, 2 falhas | 5 tarefas, 1 chamada, 0 falhas |
| `bug` | 11 tarefas, 4 chamadas | 5 tarefas, 0 chamadas |
| `multirequisito` | run **pausado**, 0/2 requisitos, nenhum arquivo criado | run concluído, 2/2 requisitos, ambos os arquivos criados |
| `verificacao_reprova` | **alterou `app.py`** contra o pedido, 36 chamadas, não reportou a reprovação | arquivo intacto, 0 chamadas extras, reprovação reportada |
| `pergunta_simples` | 2 tarefas | 2 tarefas |

### O que cada ganho veio de

| Ganho | Causa |
|-------|-------|
| Plano do modelo deixou de ser descartado | `kind: "final_answer"` rejeitava o plano inteiro (`plan_contract.py`) |
| Chamadas ao modelo caíram | cobrança única no ciclo de ferramentas quando o modelo não entrega o payload (`tool_loop.py`) |
| Falhas de modelo caíram | o `{}` do modelo não reiniciava mais a etapa; o plano reparado (`edit_anchor_missing`) e o verificador inválido são corrigidos antes de executar |
| `multirequisito` deixou de pausar | a verificação da decomposição (`stages`) conferia as etapas de verdade; o `pytest` sobre uma pasta de testes inexistente reprovava por um motivo que não era do trabalho |
| `verificacao_reprova` deixou de alterar o projeto | "não altere nenhum arquivo" virou permissão de ferramenta (`strategy.is_read_only_request`) |
| A reprovação passou a ser reportada | rodapé determinístico na resposta final (`closing.verification_footer`) |
| Requisitos comprovados subiram | o critério de aceite canônico passou a chegar ao prompt da etapa (`context/operation_builder.py`) |

### Como ler estes números

O `gpt-oss:20b` é **não determinístico**: o mesmo pedido pode produzir planos e quantidade de
chamadas diferentes. Os números acima são de execuções reais, uma por configuração; rodar a
avaliação de novo produz variação. O que se mantém estável entre execuções é a **direção**:
o plano do modelo passa a ser usado, a execução reprovada é reportada, o pedido de somente
leitura é respeitado.

## 🎯 Estratégia de resolução — medição de 20/10/2026

Medição da estratégia de resolução ([estrategia-resolucao.md](/docs/architecture/estrategia-resolucao.md)):
mesmos cinco cenários, mesmo modelo (`gpt-oss:20b` via Ollama local), três rodadas de cada lado
(15 cenários por lado). O "antes" é o commit `0e20b76`, rodado num *worktree* isolado com o mesmo
roteiro de avaliação; o "depois" é a árvore atual.

### Com o modelo real (15 cenários por lado)

| Métrica | Antes | Depois | Δ |
|---------|-------|--------|---|
| Cenários com aceite integral | 14 / 15 | **15 / 15** | +1 |
| Conclusões prematuras | 0 | 0 | — |
| Requisitos obrigatórios comprovados | 17 / 18 | 17 / 18 | — |
| Tarefas criadas | 117 | **107** | −9 % |
| Chamadas ao modelo | 76 | **50** | **−34 %** |
| Falhas de modelo | 6 | **2** | **−67 %** |
| Replanejamentos | 5 | **3** | −40 % |
| Tokens de completion | 39 640 | **36 439** | −8 % |
| Tempo total | 2 734 s | 3 015 s | +10 % |

Por rodada (aceite / chamadas ao modelo): **antes** 5/20, 4/39, 5/17 — **depois** 5/24, 5/16, 5/10.

O que a leitura honesta mostra:

- **A taxa de aceite não regrediu** e ficou mais estável: o "depois" passou nos 15 cenários; o
  "antes" perdeu um (`verificacao_reprova`, cujo run não terminou dentro do orçamento de passos).
  Com 15 cenários, a diferença de **um** cenário é compatível com a variabilidade do modelo — o que
  se pode afirmar é a **ausência de regressão**, não uma vitória estatística.
- **A chamada ao modelo caiu 34 %**, e o pior caso por rodada caiu de 39 para 24. A dispersão
  menor é o sinal mais forte: o "antes" tinha rodadas que gastavam o dobro.
- **O tempo total subiu 10 %**, puxado por uma rodada mais lenta. É o custo de manter a memória de
  abordagem no prompt (bloco de hipótese, tentativas e critérios) e de investigar antes de repetir.
- **O cenário anti-conclusão-falsa** (`verificacao_reprova`) passou em 3/3 depois (2/3 antes), e as
  chamadas ao modelo caíram de 10/8/3 para 0/0/0: o run chega à verificação e reporta sem precisar
  do modelo.

### Com falha injetada (determinístico, cenário `funcional`, 80 passos)

| Falha injetada | Chamadas antes → depois | Estagnações antes → depois | Replanejamentos antes → depois | Tarefas antes → depois |
|-----------------|-------------------------|-----------------------------|-------------------------------|------------------------|
| `invalido` (devolve prosa) | 12 → **6** | 4 → 3 | 3 → 2 | 15 → 13 |
| `vazio` (resposta vazia) | 12 → **6** | 4 → 3 | 3 → 2 | 15 → 13 |
| `http400` (pedido recusado) | 12 → **3** | 4 → **1** | 3 → **0** | 15 → **5** |
| `transitorio` (cai uma vez) | 3 → 3 | 1 → 1 | 0 → 0 | 5 → 5 |

Aqui a medição é determinística, e a direção é inequívoca: **metade das chamadas na falha de
formato, e um quarto na recusa permanente** — a falha que antes consumia três replanejamentos
inteiros e 12 chamadas idênticas. O caso transitório é idêntico nos dois lados: ele não deve ser
tratado como repetição improdutiva, e não é.

Em nenhum dos casos, antes ou depois, o run **declarou sucesso sem cumprir o objetivo**: a
aceitação foi `false` nos dois lados e nenhum arquivo foi criado à revelia. A melhoria é no
**custo da falha**, não no critério de conclusão — que é exatamente onde o risco estava.

### Limitações desta medição

- Três rodadas por lado é pouco para um modelo estocástico: as diferenças de **aceite** e de
  **tempo** estão dentro do ruído; as de **chamadas ao modelo** são mais robustas (50 contra 76,
  com pior caso menor), mas continuam sendo uma amostra.
- Os cenários da avaliação cobrem tarefas curtas. Não medem uma sessão longa de produção, que é
  onde a repetição improdutiva custava caro.
- A falha injetada é determinística por construção: ela mede a **resposta do sistema**, não a
  qualidade do modelo diante de uma falha real.
- Nenhuma medição de tokens do provedor foi feita (o Callidus estima tokens de contexto; o Ollama
  não expõe o consumo aqui).

## 🎯 qwen3:8b — servidor Ollama simulado

Medição de 22/10/2026, sem o modelo real (o Ollama não estava acessível no ambiente da auditoria).
O roteiro [`scripts/simular-qwen3.py`](/scripts/simular-qwen3.py) roda o fluxo inteiro (planejar →
ler → alterar → `pytest` → responder) contra um **servidor Ollama simulado** que reproduz o
comportamento documentado do servidor real — janela padrão de 4 096 tokens quando o corpo não traz
`num_ctx`, corte silencioso das mensagens mais antigas e do começo do texto, esquemas das
ferramentas dentro do prompt — e um "modelo" determinístico que só vê o que sobrou depois do
corte. Ele mede **o que o Callidus manda ao servidor**, não a qualidade do qwen3.

```bash
python scripts/simular-qwen3.py                      # servidor com janela padrão de 4096
python scripts/simular-qwen3.py --janela-padrao 32768  # máquina com 24–48 GiB de VRAM
```

Antes = commit `d180d09`; depois = esta entrega. Mesmos cenários, mesmo servidor simulado.

| Cenário (janela padrão 4 096) | Run antes → depois | `calc.py` corrigido | Chamadas ao modelo | Chamadas com corte | Tokens enviados |
|-------------------------------|--------------------|---------------------|--------------------|--------------------|-----------------|
| `simples` (fixture de 181 bytes) | completed → completed | sim → sim | 4 → 4 | 0 → 0 | 5 960 → 5 670 |
| `inspecao_longa` (6 leituras) | completed → completed | sim → sim | 7 → 7 | 0 → 0 | 16 236 → 15 511 |
| `arquivo_realista` (`calc.py` de ~9 KB) | **paused → completed** | **não → sim** | **20 → 6** | **18 → 0** | 106 801 → 24 394 |
| `realista_inspecao_longa` | **paused → completed** | **não → sim** | **20 → 7** | **18 → 0** | 106 801 → 30 773 |
| `pensamento_no_texto` | completed → completed | sim → sim | 4 → 4 | 0 → 0 | 5 960 → 5 670 |

Com `--janela-padrao 32768`, os cinco cenários concluem nos dois lados, com as mesmas chamadas; o
depois pede uma janela 4× menor (8 192, menos memória de KV) e manda ~4 % menos tokens. No cenário
`pensamento_no_texto`, o antes grava o `<think>` na resposta final ao usuário; o depois, não.

Como ler:

- O ganho grande depende da máquina: abaixo de 24 GiB de VRAM (o padrão de 4 096 do Ollama), um
  arquivo de tamanho comum já fazia o prompt passar da janela, e o servidor cortava o objetivo e o
  formato de saída. Com 24 GiB ou mais, o padrão do servidor já era grande o bastante.
- Os tokens menores vêm do fim do estado de tarefas irmãs nas regras do projeto
  ([orcamento-contexto.md](/docs/architecture/orcamento-contexto.md#-memória)).
- O "modelo" do simulador acerta sempre que vê a instrução: a medição não diz nada sobre a taxa
  de acerto do qwen3:8b real.

### Pendente: medição com o modelo real

```bash
scripts/medir-qwen3.sh            # 3 rodadas por lado, antes = d180d09, depois = HEAD
ROUNDS=1 scripts/medir-qwen3.sh   # uma rodada (mais rápido)
```

O roteiro baixa o modelo se faltar, roda os dois lados em *worktrees* limpos (trabalho sem commit
não contamina), alterna a ordem a cada rodada e guarda em `lab/out/qwen3/` os resumos, os bancos
de cada cenário (com `inference_records`) e o `api/ps` do Ollama.

O modelo de referência da avaliação continua `gpt-oss:20b` (decisão do dono, AGENTS.md §17); a
avaliação acima com o `qwen3:8b` ainda **não foi feita**. Rode três rodadas por lado antes de
afirmar ganho de aceite.

## 🎯 qwen3-vl:8b — modelo real, tarefa média (26–27/10/2026)

Medição com o modelo real no Mac do dono: `qwen3-vl:8b` (Q4_K_M, 8,8 B; no Ollama 0.40.3 essa tag
**é** a variante `8b-thinking`), cenário `multirequisito` (criar `soma` em `a.py` e `sub` em `b.py`,
os dois comprovados), banco e pasta isolados, 120 passos no máximo. Roteiro:
[`scripts/medir-multirequisito.sh`](/scripts/medir-multirequisito.sh); bancos de cada rodada em
`lab/out/qwen3vl*/`.

| Lado | Rodadas | Desfecho | Código certo (aceite independente) |
|------|---------|----------|-------------------------------------|
| Antes (`422a0e0`) | 3 | **3 de 3 quebraram com `ValueError`** (orçamento de contexto negativo) | — |
| 1ª correção (prova por arquivo, duplicata, `edit_file`, reserva de raciocínio) | 2 | 1 quebrou com o mesmo `ValueError`; 1 escreveu as duas funções e não fechou em 120 passos (2,3 h) | 1 de 1 que terminou |
| + bloco de raciocínio vazio, janela que acompanha a reserva, `pytest` sem testes | 1 | pausou no limite de tentativas: 0 de 2 requisitos comprovados, 43 min | sim |

Por chamada ao modelo (mesma tarefa, mesmo Mac):

| | Antes | Com o bloco de raciocínio vazio |
|---|---|---|
| Plano | 2 048 tokens de raciocínio e conteúdo **vazio** (4 de 4 cortados, 76–115 s cada) | 482–890 tokens, 37–63 s, 0 de 3 cortados |
| Operação concluída | 400–4 424 tokens, 15–295 s | 35–264 tokens, 6–27 s |
| Operações cortadas | 5 de 14 (133–548 s cada) | 6 de 30 (127–833 s cada: repetição até o limite de saída) |

O que cada achado mudou:

- **O modelo raciocina sempre.** A variante só de raciocínio ignora `think: false`; o plano gastava a
  saída inteira pensando. Agora o adaptador preenche um bloco `<think></think>` vazio e o modelo
  responde direto ([provedores.md](/docs/architecture/provedores.md)).
- **Quebra do run.** Três cortes dobravam a reserva de saída até ocupar a janela inteira; o
  orçamento de entrada ficava negativo e o processo caía com exceção. A janela agora cresce junto.
- **`pytest` sem testes.** Num projeto Python sem testes, "no tests ran" reprovava para sempre e o
  run replanejava até o limite. Agora vale a sintaxe dos `.py`.
- **Formato sem raciocínio.** Respondendo direto, o modelo escreve as chamadas de ferramenta como
  objetos JSON em linhas seguidas — era a causa das 15 falhas da última rodada ("Extra data",
  "faltam campos: path"). O adaptador e a operação passaram a ler esse formato; **essa última
  correção ainda não foi medida com o modelo real**.

Pendente: rodar `TAG=qwen3vl-final2 LADOS=depois ROUNDS=3 scripts/medir-multirequisito.sh` com o
código atual. O modelo de referência da avaliação continua `gpt-oss:20b` (decisão do dono).

## 🎯 Narração em tempo real — antes e depois (02/11/2026, `gpt-oss:20b`)

Mudança medida: o pedido de narração no formato de saída da operação
([`NARRATION_HINT`](/src/agent/context/operation_builder.py)) e o filtro de narração
([narracao-tempo-real.md](/docs/architecture/narracao-tempo-real.md)). "Antes" é o commit `440954c`
(worktree separado), "depois" é `9a225ab`; mesmo modelo, mesmo provedor, 40 passos, uma rodada por
lado. Saída: `lab/out/avaliacao-narracao-antes.json` e `lab/out/avaliacao-narracao-depois.json`.

| Medida (*medido*) | Antes | Depois |
|-------------------|-------|--------|
| Aceite | 5/6 | 6/6 |
| Runs concluídos | 4/6 | 5/6 |
| Requisitos comprovados | 5/7 | 7/7 |
| Conclusões falsas | 0 | 0 |
| Chamadas ao modelo | 125 | 38 |
| Falhas do modelo | 17 | 1 |
| Estagnações / replanejamentos | 2 / 2 | 0 / 1 |
| Tokens de saída | 37 435 | 16 441 |
| Tempo total | 1 046 s | 443 s |
| Narrações emitidas | — | 0 (em 33 chamadas de operação) |

Leitura honesta:

- **Nenhuma regressão.** Era o que esta medição precisava mostrar: o pedido de narração não piorou
  aceite, conclusões nem custo.
- **A melhora não deve ser creditada à narração.** O `gpt-oss:20b` não escreveu nenhuma narração
  (pelo Ollama, o preâmbulo vai para o canal de raciocínio), então o filtro não mudou nada, e o
  pedido no prompt foi ignorado. Com uma rodada por lado, a diferença em `bug` e `arquivo_grande`
  (que no "antes" estagnaram) está dentro da variação já vista entre rodadas deste modelo.
- **A narração com modelo real foi medida à parte**, com `qwen3-vl:8b`
  ([medidas](/docs/architecture/narracao-tempo-real.md#-medidas)).

## 🎯 Etapas 1 e 2 — confiabilidade e decomposição (02/11/2026)

Estado medido: `c545a8e` (Etapas 1 e 2) e, nos cenários `verificacao_reprova` e
`pergunta_simples`, `d10f247`. A primeira rodada com `gpt-oss:20b` caiu no quinto cenário por um
defeito **anterior** a esta entrega, que a medição revelou: o caminho "resposta final inválida"
chamava um atributo inexistente, e o passo escondia o erro. Ele foi corrigido em `d10f247`, e os dois
cenários que faltavam rodaram de novo. Mesmo provedor (`meu_ollama`), 40 passos, uma rodada por
modelo. O `qwen3:8b` não estava instalado; o modelo pequeno medido foi o `qwen3-vl:8b`. Saída:
`lab/out/avaliacao-etapas12-*.json`. A primeira rodada do `gpt-oss:20b` não gravou o JSON, porque o
processo caiu; os números dela vêm do log do terminal.

| Cenário | `gpt-oss:20b` | `qwen3-vl:8b` |
|---------|---------------|---------------|
| funcional | concluído · 1/1 · 2 chamadas · 181 s | concluído · 1/1 · 9 chamadas · 95 s |
| bug | **ativo no limite** · 0/1 · 14 chamadas · 212 s | **ativo no limite** · 0/1 · 11 chamadas · 298 s |
| arquivo_grande | **ativo no limite** · 0/1 · 24 chamadas · 377 s | **ativo no limite** · 0/1 · 11 chamadas · 1 325 s |
| multirequisito | concluído · 2/2 · 9 chamadas · 317 s | concluído · 2/2 · 17 chamadas · 154 s |
| verificacao_reprova | concluído · 1/1 · 157 s | concluído · 1/1 · 4 chamadas · 156 s |
| pergunta_simples | concluído · 1/1 · 20 s | concluído · 1/1 · 2 s |

| Resumo (*medido*) | `gpt-oss:20b` | `qwen3-vl:8b` |
|-------------------|---------------|---------------|
| Aceite objetivo | 6/6 | 6/6 |
| Conclusões falsas | 0 | 0 |
| Runs concluídos | 4/6 | 4/6 |
| Requisitos comprovados | 5/7 | 5/7 |

Leitura honesta:

- **Nenhuma conclusão falsa nos dois modelos**, e o modelo de 8B fecha os mesmos cenários que o de
  20B, sem trocar de modelo nem inferir em paralelo.
- **`bug` e `arquivo_grande` não fecham em 40 passos nos dois modelos**: o código fica certo (o aceite
  objetivo passa), mas o requisito não é comprovado antes do limite. Na medição de `9a225ab` com
  `gpt-oss:20b` os dois concluíram; na de `440954c`, estagnaram. Com uma rodada por modelo, não dá
  para separar a variação do modelo de uma regressão desta entrega. **A investigação está pendente.**
- O `qwen3-vl:8b` levou ~22 min no `arquivo_grande`; para onde vai esse tempo ainda não foi medido.

### Investigação de `bug` e `arquivo_grande` (02/11/2026)

Três defeitos achados nos runs que não fecharam, corrigidos com regressão:

| Defeito | Correção | Commit |
|---------|----------|--------|
| `git_status` numa pasta sem git devolvia "not a git repository"; a etapa repetia três vezes, idêntica, e a estagnação descartava o plano inteiro | a resposta determinística do ambiente vira a descoberta da etapa (`environment_finding`) | `6622705` |
| `run_pytest` verde concluía "sem verificador"; o requisito ficava sem prova e o trabalho era refeito até o limite | etapa que roda a suíte e passa grava a evidência do pytest | `5b74810` |
| `write_file` trocou `calc.py` (362 linhas) por 1 linha e a verificação implícita aprovou; depois, o modelo regravou o arquivo inteiro de memória alterando outras funções | escrita que apaga mais da metade de um arquivo existente reprova e é desfeita; `write_file` sobre arquivo existente com 150+ linhas é recusado (vai por `edit_file`) | `5b74810`, `27470a9` |

Medição depois das correções (uma rodada por cenário, 40 passos):

| Cenário | Antes | Depois |
|---------|-------|--------|
| `gpt-oss:20b` · bug | ativo no limite, 212 s | **concluído**, 1/1, 42 s |
| `gpt-oss:20b` · arquivo_grande | ativo no limite, 377 s | concluído, 1/1, 44 s (`6622705`); **pausado** por estagnação, aceite cumprido (`27470a9`) |
| `qwen3-vl:8b` · bug | ativo no limite, 298 s | **concluído**, 1/1, 114 s |
| `qwen3-vl:8b` · arquivo_grande | ativo no limite, outras funções apagadas | ativo no limite; com `27470a9`, funções preservadas, mas o plano não incluiu a correção |

Leitura honesta:

- **`bug` passou a fechar nos dois modelos.**
- **`arquivo_grande` continua instável.** Com `27470a9`, a recusa barrou duas reescritas
  destrutivas do `gpt-oss:20b` (uma checagem de tipos não pedida e uma etapa replanejada "trocar
  `calc.py` por uma implementação mínima"), e as 45 funções ficaram intactas. O que impede o run de
  fechar é um problema **anterior**: uma etapa "executar testes" vira operação de modelo, que exige
  uma escrita como entrega, e cada resposta sem escrita é recusada como inválida. Somam-se chamadas
  de ferramenta malformadas que o Ollama não interpreta. No `qwen3-vl:8b`, a variação entre rodadas
  domina (numa rodada o plano não trouxe a etapa de correção).
- Nenhuma rodada desta investigação terminou em conclusão falsa.

Depois de `9543fc1` (etapa que roda os testes entrega o veredito, em vez de saída inválida):

| Cenário | Resultado |
|---------|-----------|
| `qwen3-vl:8b` · arquivo_grande | **concluído**, 1/1, aceite completo (45 funções preservadas), 103 s, sem estagnação |
| `gpt-oss:20b` · arquivo_grande | ativo no limite, aceite completo; a correção foi verificada cedo, mas a etapa "executar testes" foi subdividida num plano que pedia a mesma correção de novo, e o modelo, sem nada a mudar, respondeu em texto (saída inválida) |

O caso restante é diferente do corrigido: uma **etapa de alteração cuja mudança já está feita**
ainda exige uma escrita. O detalhe das falhas dessa rodada se perdeu (a rodada seguinte usou a
mesma pasta de trabalho e sobrescreveu o banco).

Depois de `6b78e72` (alteração já feita conclui pelo critério, em vez de saída inválida), cada modelo
em pasta de trabalho própria:

| Cenário | Resultado |
|---------|-----------|
| `gpt-oss:20b` · arquivo_grande | **concluído**, 1/1, aceite completo, 3 chamadas ao modelo, 46 s, sem estagnação |
| `qwen3-vl:8b` · arquivo_grande | **concluído**, 1/1, aceite completo, 8 chamadas ao modelo, 401 s, sem estagnação |

Com isso, `bug` e `arquivo_grande` passaram a concluir nos dois modelos (uma rodada por modelo —
a variação entre rodadas continua sem medida com várias repetições, [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível)).

## 🎯 Organização de engenharia — antes e depois (04/11/2026)

A comparação específica da missão Claude foi executada entre `a43d9c3` (antes) e `550d733` (depois), com `gpt-oss:20b`, provedor local `meu_ollama`, seis cenários, 40 passos e três rodadas por lado. O script foi idêntico nos dois commits (SHA-256 `cf51ba672e95afd8f0788424015eafca6fa263bf`). Worktrees, bancos e diretórios de trabalho eram isolados; as rodadas foram alternadas.

| Indicador | Antes | Depois |
|-----------|-------|--------|
| Runs concluídos | 14/18 (77,8%) | 13/18 (72,2%) |
| Requisitos comprovados | 18/21 (85,7%) | 16/21 (76,2%) |
| Chamadas ao modelo / ferramentas | 126 / 139 | 94 / 108 |
| Falhas do modelo / replanejamentos | 6 / 4 | 4 / 6 |
| Falsas conclusões | 0 | 0 |
| Tempo total | 2 945,2 s | 2 456,0 s |
| Mediana de chamadas ao modelo / ferramentas | 35 / 44 | 31 / 33 |
| Mediana de tempo por rodada | 924,3 s | 795,3 s |

Por cenário, runs concluídos antes→depois: `funcional` 3/3→2/3, `bug` 1/3→3/3, `arquivo_grande` 3/3→2/3, `multirequisito` 3/3→2/3, `verificacao_reprova` 1/3→1/3 e `pergunta_simples` 3/3→3/3. As medianas de custo melhoraram, mas conclusão e requisitos comprovados agregados caíram. Com n=3 e a variação do modelo, a conclusão é **inconclusiva**; não se atribui o resultado à organização. Nenhuma falsa conclusão ocorreu.

Limitação observada: `aceite_total` pode contar predicados satisfeitos quando o run está `active`/`failed` ou ainda não comprovou todos os requisitos. Para confiabilidade, use status e requisitos provados. O indicador precisa de revisão com a sessão proprietária de `lab/avaliar.py`. Os seis JSONs brutos ficam localmente em `lab/out/g1-org-2026-11-04/` e não são versionados. Esta comparação fecha a pendência específica da missão, mas não fecha o G1 amplo: ainda faltam 15+ cenários, sessão longa, cobertura dos casos da auditoria, qualidade comparada, benchmark multilíngue e tokens reais do provedor.

## 🧪 Testes determinísticos

A avaliação real depende do Ollama. Os testes de unidade cobrem os mesmos comportamentos sem
modelo, com respostas controladas:

```bash
python -m pytest -q
```

| Arquivo | Cobre |
|---------|-------|
| [`tests/test_plan_contract.py`](/tests/test_plan_contract.py) | plano tolerante, verificador inexistente, edição com trecho ausente |
| [`tests/test_verification_integrity.py`](/tests/test_verification_integrity.py) | `stages` de verdade, evidência que envelhece |
| [`tests/test_context_requirements.py`](/tests/test_context_requirements.py) | requisitos no prompt, objetivo global e regras do projeto protegidos |
| [`tests/test_recovery_and_reporting.py`](/tests/test_recovery_and_reporting.py) | cancelamento previsto, suíte que reprova, rodapé da resposta final |
| [`tests/test_qwen3_ollama_policy.py`](/tests/test_qwen3_ollama_policy.py) | janela e saída explícitas, amostragem por finalidade, `<think>`/`<tool_call>` no texto |
| [`tests/test_qwen3_context.py`](/tests/test_qwen3_context.py) | conversa do ciclo dentro da janela, estado de tarefas irmãs fora das regras do projeto |
| [`tests/test_qwen3_plan_repair.py`](/tests/test_qwen3_plan_repair.py) | recuperação única do plano com esquema imposto |

Voltar: [architecture/README.md](/docs/architecture/README.md)
