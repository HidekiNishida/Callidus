# Avaliação reproduzível do Callidus

![testes](/media/icons/testes.svg){width=48}

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

O provedor e o modelo vêm da **configuração**, não do código: o cenário monta o run com
`provider`/`model_id` e o Callidus resolve pelo catálogo de provedores. Nenhum serviço externo é
usado; se o Ollama não estiver disponível, a avaliação real não pode ser feita (e isso precisa
ser dito, não estimada).

## 🧪 Cenários e critérios de aceite

| Cenário | O que mede | Critérios |
|---------|-----------|-----------|
| `funcional` | tarefa simples com critério objetivo | `app.py` passa a conter `def dobro`; a suíte passa |
| `bug` | investigação de causa raiz | `add` passa a somar; a suíte passa |
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

Voltar: [architecture/README.md](/docs/architecture/README.md)