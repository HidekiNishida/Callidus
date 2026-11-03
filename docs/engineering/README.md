# Engenharia do Callidus

Como o Callidus se organiza para desenvolver software: papéis, propriedade dos módulos, contrato de trabalho, portões e indicadores.

Voltar ao [índice da documentação](/docs/README.md)

## 📚 Documentos

| Documento | Finalidade | Quando consultar |
|-----------|------------|------------------|
| [operating-model.md](operating-model.md) | visão do fluxo inteiro e do que não existe de propósito | primeiro |
| [organization.md](organization.md) | escritórios, equipes e as três dimensões (hierarquia, papel, especialidade) | ao falar de quem faz o quê |
| [ownership.md](ownership.md) | dono de cada caminho, áreas protegidas e coordenação | antes de mexer num módulo de outra equipe |
| [responsibilities.md](responsibilities.md) | matriz de papéis, revisão e escalonamento | ao atribuir ou revisar |
| [roles/](roles/tech-lead.md) | uma página por papel (17) | para saber o limite de um papel |
| [work-contract.md](work-contract.md) | campos do contrato de trabalho e a seleção do responsável | ao criar ou depurar uma atribuição |
| [workflow.md](workflow.md) | etapas do Kanban derivadas do status | ao ler o quadro |
| [quality-gates.md](quality-gates.md) | portões G0–G4 e a avaliação em cinco dimensões | ao aprovar ou reprovar |
| [metrics.md](metrics.md) | indicadores de entrega e seus denominadores | ao medir |
| [knowledge-management.md](knowledge-management.md) | handoff e consulta entre agentes | ao passar trabalho adiante |
| [context-engineering.md](context-engineering.md) | o que a organização põe no contexto (uma linha) | ao mexer no prompt |
| [benchmarking.md](benchmarking.md) | cenários determinísticos e avaliação real | ao provar uma melhoria |
| [security-governance.md](security-governance.md) | áreas protegidas e CI sem segredo | ao mexer em segurança ou CI |
| [audit.md](audit.md) | diagnóstico do estado anterior | para saber o que já existia |
| [final-audit.md](final-audit.md) | o que foi entregue, verificado e deixado pendente | para retomar a evolução |

## 🔌 Superfícies

| Superfície | Onde |
|------------|------|
| Domínio | [organization.py](/src/agent/domain/organization.py), [work_flow.py](/src/agent/domain/work_flow.py) |
| Serviço | [organization_service.py](/src/agent/services/organization_service.py) |
| API | [organization_routes.py](/src/agent/api/organization_routes.py) |
| Interface | Inteligência → Organização ([intelligence-organization.js](/web/static/assets/app/components/intelligence-organization.js)) |
