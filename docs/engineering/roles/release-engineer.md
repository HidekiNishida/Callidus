# Release engineer

CI, portões, integração e auditoria final.

Voltar a [responsabilidades](/docs/engineering/responsibilities.md) · Catálogo: [organization.py](/src/agent/domain/organization.py)

## 🎯 Missão e equipe

| Campo | Valor |
|-------|-------|
| Id | `release_engineer` |
| Equipe | Release Office |
| Exercido por | agente lógico do Callidus |
| Especialidades | Integração e entrega |
| Autoridade | bloquear integração com portão vermelho |
| Escala para | CTO |

## 🧰 Trabalho

| Campo | Valor |
|-------|-------|
| Tarefas que assume | CI, portões, integração |
| Artefatos | python scripts/ci.py verde e commit coerente |
| Áreas de que é dono | `scripts/`, `.github/`, `pyproject.toml`, `seg:.github` |
| Revisa o trabalho de | — |
| Quem revisa este papel | CTO, Code reviewer |
| Escalona quando | publicar versão ou ligar proteção de branch (decisão do dono) |

## ✅ Critérios de qualidade

As regras do [AGENTS.md](/AGENTS.md) valem para todo papel. A aprovação passa pelos [portões](/docs/engineering/quality-gates.md); ferramentas permitidas são as do catálogo e da política de aprovação ([ferramentas.md](/docs/architecture/ferramentas.md)) — o papel não amplia permissão.
