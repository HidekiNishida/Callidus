# Responsabilidades

Matriz dos papéis: o que cada um faz, quem revisa e como a autoridade escala.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Catálogo: [organization.py](/src/agent/domain/organization.py)

## 📋 Papéis

| Papel | Equipe | Missão | Revisor padrão |
|-------|--------|--------|----------------|
| [Product Owner](roles/product-owner.md) | Direção | decide objetivos, escopo e o que exige autorização humana | — |
| [CTO](roles/cto.md) | Direção | coerência arquitetural, qualidade global e conflitos entre especialidades | Product Owner |
| [Arquiteto de software](roles/software-architect.md) | Architecture Office | fronteiras de camada, contratos e ADRs | CTO |
| [Arquiteto de soluções](roles/solutions-architect.md) | Architecture Office | desenho da solução que cruza vários módulos | Arquiteto de software |
| [Analista de requisitos](roles/requirements-analyst.md) | Product Office | requisitos verificáveis e critérios de aceite | Product Owner |
| [Planejador](roles/planner.md) | Product Office | plano, dependências e ordem de execução | Arquiteto de soluções |
| [Tech lead](roles/tech-lead.md) | Core Engineering | coordena especialistas de uma entrega e integra as partes | QA engineer |
| [Desenvolvedor backend](roles/backend-developer.md) | Core Engineering | serviços, persistência e ferramentas | QA engineer |
| [Desenvolvedor frontend](roles/frontend-developer.md) | Product Experience | interface Vue, estilo e acessibilidade | QA engineer |
| [Engenheiro de IA](roles/ai-engineer.md) | AI/Agent Engineering | orquestração, prompts, provedores e decomposição | QA engineer |
| [Engenheiro de conhecimento](roles/knowledge-engineer.md) | Knowledge Engineering | contexto, memória, grafo e skills | QA engineer |
| [QA engineer](roles/qa-engineer.md) | Quality Engineering | confere evidências e reprova o que não está comprovado | CTO |
| [Test engineer](roles/test-engineer.md) | Quality Engineering | testes determinísticos e cenários de avaliação | Code reviewer |
| [Code reviewer](roles/reviewer.md) | Quality Engineering | revisão de código: coesão, acoplamento, legibilidade | Arquiteto de software |
| [Security engineer](roles/security-engineer.md) | Quality Engineering | permissões, segredos e caminhos perigosos | CTO |
| [Knowledge steward](roles/knowledge-steward.md) | Knowledge Office | documentação canônica, ADRs e o resume.md em dia | Code reviewer |
| [Release engineer](roles/release-engineer.md) | Release Office | CI, portões, integração e auditoria final | Code reviewer |

## ⚖️ Separação entre execução, revisão e aprovação

| Regra | Onde é aplicada |
|-------|-----------------|
| Ninguém aprova o próprio trabalho | `reviewer_allowed` recusa revisor igual ao executor; a rota devolve 422 |
| O revisor precisa revisar aquele papel | `Role.reviews` e `DEFAULT_REVIEWER`; o Product Owner (humano) pode aprovar qualquer papel |
| A verificação técnica é do runtime | o `VerificationGate` grava a evidência; o modelo não se aprova |
| Reprovação bloqueia a integração | G3 reprova e a etapa vai para `REWORK` mesmo com a tarefa `COMPLETED` |

## 🪜 Escalonamento

Cada papel tem `escalates_to`. A cadeia termina no Product Owner, que decide o que o [AGENTS.md §17](/AGENTS.md#17-decisões-do-dono) reserva ao dono: modelo e provedor padrão, escopo, licença, versão, dados do usuário. Atribuição com confiança baixa (`needs_investigation`) não escolhe ao acaso: o G0 aponta a investigação antes de executar.
