# Interface web

Estáticos em [`web/static/`](/web/static/) · Análise UX: [ux-ui.md](/docs/architecture/ux-ui.md)

## Layout (v0.4)

| Zona | Função |
|------|--------|
| **Sidebar** | Projetos, busca, saúde da API |
| **Topbar** | Modelo Ollama, controles de run, aprovação de ferramentas |
| **Plano** | Composer de objetivo + árvore com badges |
| **Inspetor** | Detalhe, tentativas, evidências, git diff, ferramentas |
| **Atividade** | Feed legível + MCP discover |

## Atalhos

- `Ctrl+Enter` — executar auto
- `Ctrl+.` — um passo

## Preferências

Persistidas em `localStorage` (`agente-local-ui-v1`): último projeto, provider, modelo.

## Demo E2E

1. Projeto com path absoluto para `tests/fixtures/sample_project`
2. Template **Demo E2E** no composer
3. **Iniciar** → **Auto** (usa mock automaticamente se objetivo contém `e2e`)

Voltar: [architecture/README.md](/docs/architecture/README.md)
