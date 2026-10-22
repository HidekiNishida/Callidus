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