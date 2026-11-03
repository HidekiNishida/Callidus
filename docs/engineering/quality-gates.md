# Portões de qualidade

Os portões G0–G4 de cada tarefa: o que conferem, o que é eliminatório e de onde vem a evidência.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Código: `evaluate_gates` em [work_flow.py](/src/agent/domain/work_flow.py) · API: `GET /tasks/{id}/gates`

## 🚦 Portões

| Portão | Confere | Eliminatório | Fonte |
|--------|---------|--------------|-------|
| G0 Planejamento | objetivo, critério ou requisitos, responsável, revisor independente | sim | contrato de trabalho |
| G0 | confiança da atribuição, risco classificado | não (aviso) | contrato de trabalho |
| G1 Implementação | executada; nenhum arquivo alterado fora de `allowed_files` | sim | tentativas de escrita (`files_changed_by`) |
| G2 QA | a **última** evidência do portão de verificação aprovou | sim | `EvidenceModel` gravada pelo `VerificationGate` |
| G2 | aprovada na primeira verificação | não (retrabalho) | evidências anteriores |
| G3 Auditoria técnica | QA aprovado; nenhuma revisão independente reprovou; sem autoaprovação; área protegida ou contrato com revisão registrada | sim | `work_item.reviews` |
| G4 Integração | portões anteriores aprovados; subtarefas concluídas; sem bloqueio; tarefa concluída | sim | árvore de tarefas e status |

Estados: `passed`, `failed`, `pending` (ainda não verificável). Uma verificação eliminatória que falha reprova o portão; nenhuma média esconde a falha.

## 🔒 Independência

Os portões **não verificam nada sozinhos**: leem o que o portão único gravou e as revisões registradas. Existe um só verificador técnico (`VerificationGate` → `finalize_verification`); criar outro reabriria o verde falso que a unificação removeu ([confiabilidade-decomposicao.md](/docs/architecture/confiabilidade-decomposicao.md)).

A revisão (`POST /tasks/{id}/reviews`) exige papel que revise o executor (`reviewer_allowed`) e motivo para reprovar; caso contrário devolve 422.

## 🧮 Avaliação da entrega

`evaluate_delivery` responde por cinco dimensões — correção (G2), arquitetura (escopo e G3), qualidade (G3), manutenção e eficiência. Manutenção é `não disponível` (o Callidus ainda não mede por tarefa); eficiência compara o número de verificações até o veredito. `accepted` só é verdadeiro sem falha eliminatória e com todas as eliminatórias medidas.
