# Auditoria final da transformação organizacional

O que a missão entregou, o que foi verificado, o que ficou pendente e por quê.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Diagnóstico inicial: [audit.md](audit.md) · Checkpoint: [tarefa](/internal/tarefas/2026-11-03-transformacao-organizacional-callidus.md)

> **Auditado em:** 2026-11-04 · os resultados desta continuação estão identificados abaixo; números anteriores continuam datados de 2026-11-03.

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
| Conhecimento | handoff estruturado; consulta persistida prioriza descendentes por correspondência lexical com especialidades, com regressão determinística | busca semântica continua pendente; a ordenação heurística não infere sinônimos |
| Trabalho | contrato funcional, responsável, escopo protegido, continuidade (estado persistido) | dependências continuam em `TaskDependencyModel`, não no contrato |
| Qualidade | revisão independente, portões, reprovação bloqueia integração, testes de regressão | auditoria de manutenibilidade por tarefa (dimensão `não disponível`) |
| Autoavaliação | indicadores medidos com denominador; comparação específica antes/depois executada em 3 × 6 cenários | comparação inconclusiva; G1 amplo ainda pede ≥15 cenários e sessão longa ([G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível)) |
| Interface | área organizacional, responsáveis, portões, evidências por portão, revisão e passagem de trabalho exibida no detalhe | — |
| Engenharia | CI local e remoto, Ruff em `[dev]`, testes Python/JS/E2E | `resume.md` não pôde ser carimbado (bloqueio abaixo) |

## 🧪 Testes e resultados

| Verificação | Resultado |
|-------------|-----------|
| Suíte Python numa cópia limpa do `HEAD` | 1433 passaram (baseline) |
| Mesma cópia com as mudanças desta missão | 1461 passaram, 0 falhas (+28 testes novos) |
| `node tests/web/e2e.mjs` (navegador real) | todos os cenários passaram |
| `tests/web/organization.test.mjs` | 4 passaram após teste de carregamento do handoff (2026-11-04) |
| Testes focados de aceitação, qualidade web, consultas e API da organização | 61 passaram (2026-11-04) |
| Conferência visual com banco descartável | quadro, portões e revisão funcionando; a aprovação do QA moveu a tarefa de Auditoria técnica para Integrada |
| `python scripts/ci.py --rapido` na árvore de trabalho | tudo verde exceto `resume.md`, que reprova só por itens da outra sessão |

## ⚠️ Riscos e limitações

- **Árvore compartilhada:** 17 arquivos de outra sessão estavam modificados sem commit; o passo `resume.md` reprova por símbolos dela, e um teste (`test_edit_file_with_empty_old_string_appends`) falha só com as mudanças dela. Esta missão não tocou nem comitou esses arquivos.
- A seleção por palavras do objetivo é heurística; com confiança baixa a atribuição pede investigação em vez de esconder a dúvida.
- O revisor é registrado pela API ou pela interface; o runtime ainda não aciona uma passagem automática de revisão por papel — hoje a independência automática é a do `VerificationGate`.
- A barra de abas da Inteligência tem 12 itens e rola na horizontal em telas estreitas.

## 🔭 Recomendações

1. Ampliar G1 para ≥15 cenários, sessão longa, casos da auditoria e mais modelos/idiomas; revisar o indicador `aceite_total`, que pode ser positivo com run `active`/`failed`.
2. Implementar verificadores específicos e gate requisito → artefato → evidência para as demais classes de entrega (G16).
3. Acionar a revisão do papel de coordenação automaticamente quando o G3 ficar pendente por área protegida.

## Continuação em 2026-11-04

- Handoff renderizado junto dos portões e revisões; teste frontend confirma a leitura do endpoint e preservação do resumo.
- Consulta persistida mantém o agente alvo em primeiro lugar e ordena os descendentes por tokens compartilhados com as especialidades; ainda é uma heurística lexical.
- A conversa culinária revelou falso aceite: a tarefa pedia `style.css`, mas o modelo alterou `index.html` e evidência genérica passou. A verificação agora rejeita divergência em evidência limitada a arquivo nomeado. O site local foi refeito e validado em viewport desktop/mobile, interações, imagens e console.
- O contrato inicial agora diferencia os pisos de web, documento, planilha, apresentação e pesquisa; são critérios de execução, não verificadores automáticos do artefato final.
- G1 específico da missão executado em worktrees isolados: antes `a43d9c3` 14/18 runs e 18/21 requisitos; depois `550d733` 13/18 e 16/21. Medianas de modelo/ferramentas/tempo: 35/44/924,3 s antes e 31/33/795,3 s depois; resultado misto e inconclusivo (n=3), sem falsa conclusão. Detalhes em [benchmarking.md](/docs/engineering/benchmarking.md) e [avaliacao.md](/docs/architecture/avaliacao.md). O G1 amplo continua aberto. `lab/avaliar.py` tem alteração local de outra sessão e não foi tocado; identificou-se também que `aceite_total` não equivale a run concluído.
