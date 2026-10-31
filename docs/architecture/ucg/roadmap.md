# Roadmap do Unified Cognitive Graph (UCG)

Ordem de implementação, critérios de conclusão e checkpoint por fase.

## Sumário

1. [Princípio de execução](#princípiodeexecução)
2. [Fases e dependências](#fasesedependências)
3. [Critério de passagem de fase](#critériodepassagemdefase)
4. [Checkpoint atual](#checkpointatual)
5. [Critérios de conclusão globais](#critériosdeconclusãoglobais)
6. [Verificação](#verificação)
7. [Links cruzados](#linkscruzados)

## Princípio de execução

Cada fase tem escopo definido, produz código utilizável, possui contratos claros, testes, critérios objetivos de conclusão, documentação atualizada, preserva compatibilidade e tem mecanismo de recuperação ou rollback quando necessário. Não se para na elaboração de plano; a missão é implementar efetivamente as fases.

## Fases e dependências

| Fase | Entrega | Depende de | Critério de conclusão |
|------|---------|------------|-----------------------|
| Fase 0 | Auditoria + docs/architecture/ucg/ | — | documentos criados e revisados |
| Fase 1 | Contrato e modelo do UCG | Fase 0 | tipos de nó e relacionamento tipados, validação de aresta, provência, isolamento, testes de integridade |
| Fase 2 | Graph Foundation + Graph Query Engine | Fase 1 | consulta seletiva com limites de profundidade/nós/relações/direções/escopo/tempo/orçamento; sem vazamento entre projetos; sem ciclos infinitos |
| Fase 3 | Progressive Context Reduction | Fase 2 | catálogos não carregados integralmente; conteúdo sob demanda; orçamento respeitado; seleção explicável; testes de falso positivo/negativo |
| Fase 4 | Capability Graph — Skills, MCPs, ferramentas | Fase 3 | dependências resolvidas, disponibilidade com TTL, permissões preservadas, descoberta seletiva |
| Fase 5 | Memory Graph | Fase 3 | camadas imediata/tarefa/projeto/arquivo, validade, confiança, promoção controlada, conflitos identificáveis |
| Fase 6 | Execution Graph e orquestração | Fase 4, Fase 5 | DAG respeitado, ciclos bloqueantes detectados, retomada preservada, reutilização segura de resultados |
| Fase 7 | Agent Graph | Fase 6 | perfis de agente, seleção por competência, contexto mínimo, handoff estruturado |
| Fase 8 | Knowledge Gap Resolver + Research Graph | Fase 2, Fase 5 | lacunas detectáveis, busca orientada, reutilização de descobertas, provência, controle de atualidade |
| Fase 9 | Decision Graph | Fase 5 | decisões vinculadas a tarefas, evidências vinculadas a hipóteses, alternativas rejeitadas consultáveis |
| Fase 10 | Quality Graph | Fase 6, Fase 9 | critérios antecipados, cobertura de requisitos, evidências rastreáveis, verificação incremental |
| Fase 11 | Strategy Graph | Fase 10 | métricas persistidas, estratégias classificáveis, seleção explicável, aprendizado gradual, reversão |
| Fase 12 | Observabilidade e interface | Fase 11 | métricas de exposição, diagnóstico de seleção, inspeção de tarefa |
| Fase 13 | Benchmark, estabilização e ativação gradual | todas | suíte de cenários reproduzíveis, comparação antes/depois, metas quantitativas, ci.py verde |

A ordem de detalhes internos pode ser ajustada quando houver dependências comprovadas, mas nenhum domínio ou critério é eliminado sem justificativa registrada em [decisoes.md](decisoes.md).

## Critério de passagem de fase

Uma fase só está concluída quando:

1. O código correspondente existe.
2. As integrações necessárias funcionam.
3. Os testes estão passando, descontadas e documentadas as falhas preexistentes.
4. A documentação está sincronizada.
5. O checkpoint foi atualizado.
6. Não existem regressões conhecidas sem tratamento.

Se uma fase possuir um bloqueio real: investigue, tente alternativas, registre a causa, implemente componentes independentes, não declare conclusão falsa e continue as etapas que não dependem daquele bloqueio, quando seguro.

## Checkpoint atual

| Campo | Valor |
|-------|-------|
| Fase em execução | Fase 11 — Strategy Graph (concluída) |
| Última entrega | `src/agent/knowledge/ucg/` (model, graph, query, reduction, capability, memory, execution, agent, research, decision, quality, strategy) + ~85 testes |
| Testes relevantes executados | Suíte completa verde: 1268 testes passando na última execução |
| Próxima etapa | Nenhuma — todas as Fases 0–11 implementadas |
| Bloqueios | nenhum |

O checkpoint é mantido nesta própria seção do roadmap e permite que outro agente retome o desenvolvimento sem reconstruir o histórico.

## Critérios de conclusão globais

Ao terminar, o Callidus deverá possuir conhecimento integrado, memória inteligente, capacidades inteligentes, planejamento eficiente, execução resiliente, agentes especializados, pesquisa integrada, qualidade, aprendizado operacional e eficiência mensurável, conforme a especificação do UCG, sem regressão na qualidade e sem dependência de modelos grandes.

## Verificação

```bash
source .venv/bin/activate && python scripts/ci.py --rapido
python -m pytest -q
```

## Links cruzados

- [auditoria do UCG](auditoria.md)
- [decisões do UCG](decisoes.md)
- [Visão geral da arquitetura](../visao-geral.md)
- [Roadmap do projeto](../../../docs/progresso/roadmap.md)
