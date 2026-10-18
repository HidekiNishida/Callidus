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

## Envio de mensagens

- A mensagem aparece no chat (bolha “Enviando…”) e o campo é limpo **antes** de qualquer chamada à API; se a criação da tarefa falhar, o texto e os anexos voltam ao campo.
- Só existe **uma execução por vez**: enquanto houver envio em andamento ou run ativo (`/projects/{id}/live` → `run`), o botão de enviar vira **Parar** (cancela o run) e Enter/edição de mensagem só mostram um aviso, sem enviar.
- O bloqueio termina quando o run é cancelado ou quando o servidor deixa de reportar run ativo (consultado pelo polling).

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
