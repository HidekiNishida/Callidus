# Gestão do conhecimento

Como o conhecimento passa de um agente para outro sem que alguém precise conhecer o projeto inteiro.

Voltar ao [hub de engenharia](/docs/engineering/README.md)

## 🔁 Handoff

Quando uma tarefa devolve resultado ao pai (`AgentService.record_task_result`), o `OrganizationService.record_handoff` grava no agente um resumo estruturado, montado só do estado persistido — reaproveita `structured_summary` de [subtask_summary.py](/src/agent/orchestrator/subtask_summary.py), sem inferência:

| Campo | Origem |
|-------|--------|
| `task_id`, `work_item_id`, `from_agent_id`, `from_role`, `next_owner` | tarefa, contrato e revisor |
| `findings`, `decisions`, `problems`, `limitations`, `pending`, `next_action` | resumo estruturado |
| `files_examined`, `files_changed`, `tests_run` | tentativas de ferramenta e de verificação |
| `hypotheses`, `discarded_hypotheses` | descobertas do agente com `kind="hypothesis"` / `"discarded_hypothesis"` |
| `evidence_ids`, `results` | evidências e resultado consolidado |

A rota `GET /tasks/{id}/handoff` monta o mesmo resumo na hora, para qualquer tarefa.

## 🔎 Consulta entre agentes

Continua no `QueryService`: responde primeiro do que está persistido (`answer_from_persisted`) e só usa inferência quando necessário, sempre com a origem da resposta. O papel e as especialidades do agente agora ficam em `metadata_json["assignment"]`, consultáveis por `GET /organization?project_id=…`. A busca por especialidade dentro do `QueryService` ainda é lexical — lacuna registrada no [G7](/docs/progresso/gaps.md#g7-seleção-lexical-de-skills-estratégia-e-consulta).

## 🗄️ Decisões e confiança

Decisão estrutural vira ADR em [docs/architecture/](/docs/architecture/README.md). O conhecimento persistido distingue confirmado, hipótese e desatualizado nos mecanismos já existentes (memória operacional e Knowledge Engine — [knowledge-engine.md](/docs/architecture/knowledge-engine.md)); este modelo não cria um terceiro.
