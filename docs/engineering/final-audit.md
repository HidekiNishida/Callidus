# Auditoria final da transformação organizacional

O que a missão entregou, o que foi verificado, o que ficou pendente e por quê.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Diagnóstico inicial: [audit.md](audit.md) · Checkpoint: [tarefa](/internal/tarefas/2026-11-03-transformacao-organizacional-callidus.md)

> **Auditado em:** 2026-11-03 · cada número abaixo é *medido* nesta data, salvo quando marcado.

## 📌 Resumo executivo

O Callidus passou a ter uma organização de engenharia **implementada**, não só descrita: catálogo de equipes, papéis e propriedade no domínio; atribuição determinística gravada quando o agente nasce; contrato de trabalho, handoff estruturado, portões G0–G4 e avaliação em cinco dimensões calculados do estado persistido; revisão independente que pode reprovar; indicadores de entrega com denominador; API e aba Organização na interface; CI remoto. Não houve coluna nova, segunda máquina de estados, segundo verificador nem inferência nova.

## 🏗️ Arquitetura antes e depois

| Camada | Novo | Alterado (aditivo) |
|--------|------|--------------------|
| Domínio | `domain/organization.py`, `domain/work_flow.py` (puros; teste prova que não importam FastAPI/SQLAlchemy) | — |
| Aplicação | `services/organization_service.py` | `AgentService.ensure_agent` (atribui), `record_task_result` (handoff), `AnalyticsService.delivery_metrics` |
| Infraestrutura | — | nenhuma (usa `metadata_json` existente) |
| Apresentação | `api/organization_routes.py`, `components/intelligence-organization.js` | `api/main.py` (registro), `main.js` (aba), `style.css` |
| Contexto | — | `OperationContextBuilder._contract_block` (uma linha de responsabilidade) |

## ✅ Critérios da missão

| Área | Atendido | Pendente |
|------|----------|----------|
| Organização | organograma, papéis, especialidades, ownership rastreável, autoridade, seleção funcional | — |
| Conhecimento | handoff estruturado, contexto seletivo, decisões preservadas no contrato | busca semântica por especialidade no `QueryService` ([G7](/docs/progresso/gaps.md#g7-seleção-lexical-de-skills-estratégia-e-consulta)) |
| Trabalho | contrato funcional, responsável, escopo protegido, continuidade (estado persistido) | dependências continuam em `TaskDependencyModel`, não no contrato |
| Qualidade | revisão independente, portões, reprovação bloqueia integração, testes de regressão | auditoria de manutenibilidade por tarefa (dimensão `não disponível`) |
| Autoavaliação | indicadores medidos com denominador, comparação entre versões por projeto | avaliação real antes/depois com modelo local ([G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível)) |
| Interface | área organizacional, responsáveis, portões, evidências por portão, revisão | handoff ainda não aparece na aba (só na API) |
| Engenharia | CI local e remoto, Ruff em `[dev]`, testes Python/JS/E2E | `resume.md` não pôde ser carimbado (bloqueio abaixo) |

## 🧪 Testes e resultados

| Verificação | Resultado |
|-------------|-----------|
| Suíte Python numa cópia limpa do `HEAD` | 1433 passaram (baseline) |
| Mesma cópia com as mudanças desta missão | 1461 passaram, 0 falhas (+28 testes novos) |
| `node tests/web/e2e.mjs` (navegador real) | todos os cenários passaram |
| `tests/web/organization.test.mjs` | 3 passaram |
| Conferência visual com banco descartável | quadro, portões e revisão funcionando; a aprovação do QA moveu a tarefa de Auditoria técnica para Integrada |
| `python scripts/ci.py --rapido` na árvore de trabalho | tudo verde exceto `resume.md`, que reprova só por itens da outra sessão |

## ⚠️ Riscos e limitações

- **Árvore compartilhada:** 17 arquivos de outra sessão estavam modificados sem commit; o passo `resume.md` reprova por símbolos dela, e um teste (`test_edit_file_with_empty_old_string_appends`) falha só com as mudanças dela. Esta missão não tocou nem comitou esses arquivos.
- A seleção por palavras do objetivo é heurística; com confiança baixa a atribuição pede investigação em vez de esconder a dúvida.
- O revisor é registrado pela API ou pela interface; o runtime ainda não aciona uma passagem automática de revisão por papel — hoje a independência automática é a do `VerificationGate`.
- A barra de abas da Inteligência tem 12 itens e rola na horizontal em telas estreitas.

## 🔭 Recomendações

1. Medir com `lab/avaliar.py` (mesmo modelo, antes/depois) se a linha de responsabilidade no contexto muda a taxa de conclusão.
2. Mostrar o handoff no detalhe da tarefa na aba Organização.
3. Usar `assignment.specialties` no `QueryService` para rotear consultas por especialidade (G7).
4. Acionar a revisão do papel de coordenação automaticamente quando o G3 ficar pendente por área protegida.
