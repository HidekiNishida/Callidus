# Propriedade dos módulos

Quem é dono de cada caminho, o que é área protegida e quando a mudança exige coordenação.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Regras: `OWNERSHIP` em [organization.py](/src/agent/domain/organization.py) · API: `GET /organization/owner?path=…`

## 📐 Como a regra é escolhida

`owner_of(path)` devolve **uma** regra — a mais específica:

| Forma do padrão | Exemplo | Peso |
|-----------------|---------|------|
| Arquivo exato | `src/agent/domain/state_machine.py` | maior |
| Prefixo de pasta | `src/agent/persistence/` | pelo tamanho do prefixo |
| Pasta em qualquer nível | `seg:tests` | médio |
| Extensão | `ext:.py` | menor |

As regras de prefixo descrevem o repositório do próprio Callidus; as de pasta e extensão valem em qualquer projeto que ele edite. `validate_catalog()` reprova padrão repetido (dois donos) e área protegida sem regra de coordenação — o teste `tests/test_organization.py` roda essa conferência.

## 🗂️ Mapa do Callidus

| Caminho | Equipe | Especialidade | Protegido | Coordena com |
|---------|--------|---------------|-----------|--------------|
| `src/agent/domain/` | Core Engineering | domínio | contrato | Arquiteto de software |
| `src/agent/domain/state_machine.py` | Core Engineering | domínio | sim | Arquiteto de software |
| `src/agent/services/` | Core Engineering | engenharia de software | — | — |
| `src/agent/persistence/` | Core Engineering | dados | sim | Arquiteto de software |
| `src/agent/config.py` | Core Engineering | engenharia de software | sim | Product Owner (modelo e provedor padrão) |
| `src/agent/orchestrator/` | AI/Agent Engineering | orquestração | — | — |
| `src/agent/context/`, `knowledge/`, `memory/`, `skills/` | Knowledge Engineering | recuperação de conhecimento | — | — |
| `src/agent/providers/` | Integrations Engineering | integração de modelos | — | — |
| `src/agent/tools/`, `mcp/`, `remote/`, `automation/` | Integrations Engineering | ferramentas | — | — |
| `src/agent/security/` | Quality Engineering | segurança | sim | Security engineer |
| `src/agent/verification/` | Quality Engineering | verificação | contrato | QA engineer |
| `src/agent/intelligence/`, `observability/` | Quality Engineering | métricas | `observability/` é contrato | Arquiteto de software |
| `src/agent/api/` | Product Experience | API | contrato | Arquiteto de software |
| `web/static/` | Product Experience | interface | — | — |
| `tests/`, `lab/` | Quality Engineering | testes, avaliação | `lab/avaliar.py` | CTO (critério de avaliação) |
| `AGENTS.md`, `docs/regras/` | Knowledge Office | escrita técnica | sim | CTO |
| `docs/` | Knowledge Office | escrita técnica | — | — |
| `scripts/`, `.github/`, `pyproject.toml` | Release Office | integração | `.github/`, `pyproject.toml` | CTO, Product Owner |
| `data/` | Direção | — | sim | Product Owner |

## 🤝 Sobreposição

Um arquivo tem um dono principal. Quando o escopo de uma tarefa cruza áreas, a maioria dos arquivos decide o responsável e as demais entram em `assignment.coordination`; mudança em área protegida ou contrato compartilhado só passa no G3 com revisão registrada de um papel independente ([quality-gates.md](quality-gates.md)).
