# Interface web

<p align="center">
  <img src="/web/static/assets/brand/callidus-wordmark.svg" alt="Callidus" width="300" />
</p>

Estáticos em [`web/static/`](/web/static/) · Análise UX: [ux-ui.md](/docs/architecture/ux-ui.md)

## Identidade visual (Callidus)

| Peça | Arquivo | Onde aparece |
|------|---------|--------------|
| Símbolo | [`web/static/assets/brand/callidus-mark.svg`](/web/static/assets/brand/callidus-mark.svg) | Bolhas de mensagem do agente, estado vazio do chat, kicker do quadro ao vivo |
| Símbolo (inline) | [`web/static/assets/brand/callidus-mark-current.svg`](/web/static/assets/brand/callidus-mark-current.svg) | Mesma forma com `currentColor`, para o SVG inline do `app.js` |
| Lockup horizontal | [`web/static/assets/brand/callidus-lockup.svg`](/web/static/assets/brand/callidus-lockup.svg) | Cabeçalho da sidebar (símbolo + "CALLIDUS") |
| Lockup vertical | [`web/static/assets/brand/callidus-lockup-vertical.svg`](/web/static/assets/brand/callidus-lockup-vertical.svg) | Cabeçalhos de doc |
| Wordmark | [`web/static/assets/brand/callidus-wordmark.svg`](/web/static/assets/brand/callidus-wordmark.svg) | Só o nome "CALLIDUS" |
| Favicon | [`web/static/assets/brand/favicon.svg`](/web/static/assets/brand/favicon.svg) | Aba do navegador (`<link rel="icon">`) |

A marca é injetada na interface em dois lugares:

- **HTML estático** — `index.html` usa `<img>` para o lockup da sidebar, o símbolo no kicker e o favicon.
- **JS** — `app.js` define `BRAND_NAME` e `brandMark()`, que desenha o símbolo em SVG inline (`currentColor` no "C", azul `#668DF7` na estrela) para as bolhas de chat e o estado vazio. O nome exibido nas mensagens vem de `CHAT[locale].agent`, que vale `Callidus` em pt/en/es.

Os arquivos de origem (CorelDRAW) ficam em [`media/`](/media/) e são a fonte de verdade da marca. As versões web em `web/static/assets/brand/` são geradas por [`scripts/build_brand_assets.py`](/scripts/build_brand_assets.py) — rode o script depois de trocar qualquer SVG em `media/`.

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

Persistidas em `localStorage` (`callidus-ui-v1`): último projeto, provider, modelo. A chave legada `agente-local-ui-v1` ainda é lida na primeira visita e é apagada na primeira gravação.

## Demo E2E

1. Projeto com path absoluto para `tests/fixtures/sample_project`
2. Template **Demo E2E** no composer
3. **Iniciar** → **Auto** (usa mock automaticamente se objetivo contém `e2e`)

Voltar: [architecture/README.md](/docs/architecture/README.md)
