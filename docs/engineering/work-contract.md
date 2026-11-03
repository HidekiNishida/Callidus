# Contrato de trabalho

O que toda tarefa carrega para ser distribuída, executada, revisada e retomada — e de onde vem cada campo.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Código: [organization_service.py](/src/agent/services/organization_service.py) · API: `GET /tasks/{id}/work-item`

## 🧾 Onde fica

No `metadata_json["work_item"]` da tarefa (campo existente; nenhuma coluna nova) e, resumido, no `metadata_json["assignment"]` do agente. É gravado quando o agente nasce (`AgentService.ensure_agent`) e quando uma revisão é registrada. As rotas de leitura **calculam sem gravar**, para abrir o quadro não reescrever o banco.

## 🧩 Campos

| Campo do contrato | Origem | Usado por |
|-------------------|--------|-----------|
| `id` | equipe + início do id da tarefa | quadro e handoff |
| `objective` | `TaskModel.objective` | G0 |
| `assignment.team`, `role`, `reviewer_role` | `select_assignment` sobre o escopo | contexto, G0, G3, revisão |
| `assignment.specialties`, `skills` | regra de propriedade + especialidade líder da estratégia | seleção de skills (mesmos ids de `skills/`) |
| `assignment.domain`, `complexity`, `risk` | propriedade e tamanho do escopo | quadro, G0 |
| `assignment.rationale`, `confidence`, `needs_investigation` | seleção | justificativa rastreável; investigação quando a confiança é baixa |
| `assignment.affected_modules`, `protected_files`, `shared_contracts`, `coordination` | regras de propriedade | contexto, G3 |
| `scope.allowed_files` | `metadata_json["allowed_files"]` da tarefa (já aplicado pelo executor) | G1 |
| `acceptance.criteria`, `verification_methods` | critério da tarefa; requisitos do contrato da raiz | G0, G2 |
| `reviews` | `POST /tasks/{id}/reviews` | G3 e indicadores |
| `history` | mudança de responsável quando escopo ou objetivo mudam | auditoria |
| `handoff` (no agente) | `record_handoff` | quem continua |

Requisitos, dependências e evidências **não são copiados**: continuam no contrato da raiz (`requirements.py`), em `TaskDependencyModel` e em `EvidenceModel`, e o contrato aponta para eles.

## 🎯 Seleção do responsável

A ordem de evidência é: arquivos do escopo, especialidade líder da estratégia (`ProfessionalStrategy.lead_specialty`), palavras do objetivo. A tarefa raiz fica com o tech lead. Exemplo verificado em `tests/test_organization.py`:

```text
Escopo: src/agent/persistence/models.py
Equipe: Core Engineering · Papel: Desenvolvedor backend · Especialidade: dados
Revisor: QA engineer · Risco: alto · Coordenação: Arquiteto de software
Justificativa: 1 de 1 arquivo(s) do escopo pertencem a Core Engineering; toca área protegida
```
