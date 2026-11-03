# Governança de segurança

Como papéis e propriedade se somam às proteções que o Callidus já tinha — sem ampliar permissão nenhuma.

Voltar ao [hub de engenharia](/docs/engineering/README.md)

## 🛡️ O que já protegia e continua

| Proteção | Onde |
|----------|------|
| Caminho fora da raiz recusado | `src/agent/security/paths.py` |
| Aprovação granular de ferramenta arriscada | `ApprovalService` |
| Escopo de escrita da etapa | `allowed_files` aplicado pelo executor |
| Verificação independente | `VerificationGate` |

## ➕ O que a organização acrescenta

- `src/agent/security/` é área protegida com coordenação do security engineer; mudança ali fica em auditoria técnica até revisão registrada.
- `data/`, `src/agent/config.py` e `pyproject.toml` têm o Product Owner como coordenação: são as decisões do [AGENTS.md §17](/AGENTS.md#17-decisões-do-dono) (dados do usuário, modelo e provedor padrão, dependências).
- Papel não concede ferramenta: as permissões continuam vindo do catálogo e da política de aprovação.

## ☁️ CI remoto

`.github/workflows/ci.yml` roda com `permissions: contents: read`, sem segredo e sem modelo real. Proteção de branch **não** foi configurada (decisão do dono); o check a exigir para integrar é `ci / portões (scripts/ci.py)`.
