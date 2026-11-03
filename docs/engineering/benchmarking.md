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

A organização é determinística e não muda o que o modelo recebe além de uma linha de contexto. **Não há medição real antes/depois desta mudança** com `gpt-oss:20b` ou Qwen; ela fica pendente no [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível). Nenhum ganho de eficiência é afirmado.
