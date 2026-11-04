# Avaliação e benchmarking

Como uma mudança na organização prova que ajudou — e o que ainda não foi medido.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Método: [avaliacao.md](/docs/architecture/avaliacao.md) · Benchmarks da Inteligência: [benchmarks.md](/docs/intelligence/benchmarks.md)

## 🧪 Dois níveis

| Nível | Onde | Roda na CI? |
|-------|------|-------------|
| Cenários determinísticos A–J da organização | `tests/test_organization_api.py` | sim |
| Avaliação real com modelo local | `lab/avaliar.py` (banco isolado, mesmo modelo antes e depois) | não — lenta e não determinística |

## ⚖️ Regra de comparação

Mesmo cenário, modelo, provedor, configuração, orçamento e critério de aceite, com o número de repetições declarado. O critério de avaliação é área protegida (`lab/avaliar.py`, coordenação do CTO): mudar o critério para melhorar a nota é exatamente o que a proteção evita.

## 📌 Estado

A organização é determinística e não muda o que o modelo recebe além de uma linha de contexto. A comparação específica da missão foi executada em 2026-11-04; o G1 amplo segue aberto porque esta amostra tem só seis cenários curtos.

## 🔬 Organização de engenharia — antes e depois (2026-11-04)

Comparação entre `a43d9c3` (antes) e `550d733` (depois), com o mesmo `lab/avaliar.py` (SHA-256 `cf51ba672e95afd8f0788424015eafca6fa263bf`), provedor local `meu_ollama`, modelo `gpt-oss:20b`, seis cenários, `--max-steps 40` e três rodadas por versão. Cada execução usou worktree, banco e diretório de trabalho isolados; as rodadas foram alternadas antes/depois para reduzir efeitos de ordem.

| Indicador agregado | Antes | Depois |
|--------------------|-------|--------|
| Runs concluídos | 14/18 (77,8%) | 13/18 (72,2%) |
| Requisitos comprovados | 18/21 (85,7%) | 16/21 (76,2%) |
| Chamadas ao modelo | 126 | 94 |
| Chamadas a ferramentas | 139 | 108 |
| Falhas de chamada do modelo | 6 | 4 |
| Replanejamentos | 4 | 6 |
| Falsas conclusões | 0 | 0 |
| Tempo total | 2 945,2 s | 2 456,0 s |

| Mediana entre as três rodadas | Antes | Depois |
|------------------------------|-------|--------|
| Runs concluídos | 5/6 | 5/6 |
| Requisitos comprovados | 6/7 | 6/7 |
| Chamadas ao modelo | 35 | 31 |
| Chamadas a ferramentas | 44 | 33 |
| Falhas de chamada do modelo | 1 | 1 |
| Replanejamentos | 1 | 2 |
| Tempo por rodada | 924,3 s | 795,3 s |

Por cenário, a conclusão foi: `funcional` 3/3→2/3; `bug` 1/3→3/3; `arquivo_grande` 3/3→2/3; `multirequisito` 3/3→2/3; `verificacao_reprova` 1/3→1/3; `pergunta_simples` 3/3→3/3. Os requisitos provados foram, respectivamente, 3/3→3/3, 2/3→3/3, 3/3→2/3, 6/6→4/6, 1/3→1/3 e 3/3→3/3.

**Conclusão:** resultado inconclusivo e misto. As medianas de chamadas e tempo diminuíram, mas a taxa agregada de conclusão e de requisitos provados também caiu; com três repetições por lado e um modelo estocástico, não se atribui causalidade nem se declara ganho de confiabilidade. Nenhuma falsa conclusão ocorreu.

**Limite da métrica:** `aceite_total` agrega predicados de aceite mesmo quando o run termina `active`/`failed` ou não comprova todos os requisitos. Por isso, não deve ser tratado como taxa de conclusão; nesta comparação, status do run e requisitos comprovados são as medidas principais. A correção desse indicador deve ser feita com posse coordenada de `lab/avaliar.py`.

Resultados brutos locais: `lab/out/g1-org-2026-11-04/avaliacao-g1-org-{before,after}-r{1,2,3}.json` (ignorados pelo Git conforme a política de `lab/out/`). O G1 amplo ainda exige ≥15 cenários, sessão longa, cobertura dos casos da auditoria, comparação da disposição de qualidade, benchmark multilíngue e tokens medidos no provedor.
