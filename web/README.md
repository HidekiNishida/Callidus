# Interface web (`web/`)

SPA servida pela API em `/` — **Vue 3** (build global, sem etapa de build), com tema claro/escuro.

| Caminho | Conteúdo |
|---------|----------|
| [static/index.html](/web/static/index.html) | Shell da aplicação (monta o Vue em `#app`) |
| [static/assets/app/](/web/static/assets/app/) | Código da interface: `main.js` (bootstrap), `store.js` (estado e ações), `api.js` (HTTP + SSE), `ui.js` (ícones, markdown, formatadores) e `components/` (sidebar, topbar, chat, detalhes, provedores, ao vivo, ajustes, paleta de comandos) |
| [static/assets/app/style.css](/web/static/assets/app/style.css) | Sistema visual: tokens, tema claro/escuro, responsivo (desktop/tablet/celular) e animações |
| [static/assets/vendor/vue.global.prod.js](/web/static/assets/vendor/vue.global.prod.js) | Vue 3.5.13 (MIT) versionado localmente — a interface funciona offline |
| [static/assets/brand/](/web/static/assets/brand/) | Símbolo, lockup e favicon (gerados por `scripts/build_brand_assets.py`) |

Doc: [frontend.md](/docs/architecture/frontend.md) · UX: [ux-ui.md](/docs/architecture/ux-ui.md)

Voltar: [README](/README.md)
