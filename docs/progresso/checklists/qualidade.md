# Checklist — qualidade

Portões de qualidade, fiscais das regras e documentação.

Voltar: [checklists/](/docs/progresso/checklists/README.md)

> **Revisado em:** 2026-11-04 · **Atualizado em:** 2026-11-04 · **Mudança:** minor (G16: fidelidade da entrega)

**Resumo:** ~80 % (estimado), 16 h restantes.

| Item | Esperado | Estado | Status / horas |
|------|----------|--------|----------------|
| Comando único de verificação | um comando roda todos os portões | `python scripts/ci.py` | ✅ |
| CI remoto | cada push verificado | não existe (adiado pelo dono) | ☐ [G6](/docs/progresso/gaps.md#g6-fiscais-automáticos-das-regras-de-engenharia) |
| Lint configurado | `ruff` nas deps e com regras | usado, mas fora do `pyproject.toml` | 🟡 [G6](/docs/progresso/gaps.md#g6-fiscais-automáticos-das-regras-de-engenharia) |
| Fiscal das camadas | domínio sem FastAPI/SQLAlchemy | só revisão | ☐ [G6](/docs/progresso/gaps.md#g6-fiscais-automáticos-das-regras-de-engenharia) |
| Documentação navegável | links, referências, estrutura, `resume.md` | quatro verificações automáticas | ✅ |
| Versão e licença | uma versão; licença na raiz | divergem / ausente | ☐ [G13](/docs/progresso/gaps.md#g13-versão-e-licença) · 1 h |
| Limitações em dia | numeração e contagens corretas | desatualizado | ☐ [G14](/docs/progresso/gaps.md#g14-documentação-de-limitações-desatualizada) · 1 h |
| Requisito ligado ao artefato e evidência | tarefa com arquivo nomeado não passa por evidência de outro arquivo; interface revisada com interação | divergência de caminho reprovada; amostra web corrigida e exercitada | 🟡 [G16](/docs/progresso/gaps.md#g16-fidelidade-do-artefato-e-verificação-da-entrega) · 8 h |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-11-04 | minor | Requisito e evidência vinculados; fiscalização genérica para outros tipos de artefato ainda pendente |
| 2026-10-21 | major | Criação |
