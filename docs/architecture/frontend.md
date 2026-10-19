# Interface web

<p align="center">
  <img src="/web/static/assets/brand/callidus-wordmark.svg" alt="Callidus" width="300" />
</p>

Estáticos em [`web/static/`](/web/static/) · Análise UX: [ux-ui.md](/docs/architecture/ux-ui.md)

A interface é uma **SPA em Vue 3** (build global versionado localmente, sem etapa de build),
servida pela API em `/`. Ela conversa só com a API HTTP — nenhuma regra de negócio no navegador.

## Arquitetura

| Arquivo | Responsabilidade |
|---------|------------------|
| [`index.html`](/web/static/index.html) | Shell mínimo: monta o Vue em `#app`, carrega o vendor e o bundle |
| [`assets/vendor/vue.global.prod.js`](/web/static/assets/vendor/vue.global.prod.js) | Vue 3.5.13 (MIT) versionado — a interface funciona offline |
| [`assets/app/main.js`](/web/static/assets/app/main.js) | Bootstrap do app, componentes, modais (projeto, pasta) |
| [`assets/app/store.js`](/web/static/assets/app/store.js) | Estado reativo (Vue `reactive`) + ações (conversas, run, provedores) |
| [`assets/app/api.js`](/web/static/assets/app/api.js) | Cliente HTTP (JSON) com mensagem de erro legível |
| [`assets/app/ui.js`](/web/static/assets/app/ui.js) | Ícones SVG, markdown leve, formatadores, status |
| [`assets/app/live-state.js`](/web/static/assets/app/live-state.js) | Redutor puro do acompanhamento (tarefas, saídas, arquivos, verificações) |
| [`assets/app/live-stream.js`](/web/static/assets/app/live-stream.js) | Conexão SSE com reconexão e cursor do último `seq` |
| [`assets/app/live-view.js`](/web/static/assets/app/live-view.js) | Renderizadores do painel de acompanhamento (usados pelo redutor) |
| [`assets/app/components/`](/web/static/assets/app/components/) | `sidebar`, `topbar`, `chat`, `details`, `live`, `providers` |
| [`assets/app/style.css`](/web/static/assets/app/style.css) | Sistema visual: tokens, tema claro/escuro, componentes |

O redutor (`live-state.js`) e os renderizadores (`live-view.js`) são os mesmos testados pelo Node
([`tests/web/`](/tests/web/)) — o painel de acompanhamento não tem lógica duplicada.

## Telas

| Tela | Onde | O que faz |
|------|------|-----------|
| **Conversa** | Aba na topbar | Chat com o agente, etapas da execução, anexos, escolha de provedor/modelo/navegador e controles do run |
| **Acompanhamento** | Aba na topbar (habilitada com run ativo) | Plano da execução, chamadas ao modelo em streaming, arquivos, verificações, atividade e métricas |
| **Provedores** | Aba na topbar | Configuração de provedores: criar, editar, testar conexão, listar modelos, definir o padrão, gravar/apagar credencial |

## Configuração de provedores pela interface

A tela **Provedores** grava a configuração declarativa (YAML ou JSON) e mantém as credenciais
fora do repositório:

| Ação | Chamada | Efeito |
|------|---------|--------|
| Listar | `GET /providers/config` | Provedores configurados + caminho do arquivo + situação da credencial (nunca o valor) |
| Salvar | `PUT /providers/config` | Valida tipo/URL/nome e grava o arquivo |
| Remover | `DELETE /providers/config/{nome}` | Tira o provedor (e a credencial gravada) |
| Credencial | `PUT /providers/config/{nome}/secret` | Grava a chave em `data/secrets/{nome}.key` com permissão `0600` e aponta a configuração para ela |
| Apagar credencial | `DELETE /providers/config/{nome}/secret` | Remove o arquivo da chave |
| Testar | `POST /providers/{nome}/test` | Conectividade sem inferência (lista os modelos) |
| Modelos | `GET /providers/{nome}/models` | Catálogo do servidor (com cache no provedor) |

A chave também pode continuar vindo do ambiente (`api_key_env`), que é a opção preferida em
servidores com variáveis de ambiente.

## Identidade visual (Callidus)

| Peça | Arquivo | Onde aparece |
|------|---------|--------------|
| Símbolo | [`web/static/assets/brand/callidus-mark.svg`](/web/static/assets/brand/callidus-mark.svg) | Bolhas de mensagem do agente, estado vazio do chat |
| Lockup horizontal | [`web/static/assets/brand/callidus-lockup.svg`](/web/static/assets/brand/callidus-lockup.svg) | Cabeçalho da sidebar (símbolo + "CALLIDUS") |
| Lockup vertical | [`web/static/assets/brand/callidus-lockup-vertical.svg`](/web/static/assets/brand/callidus-lockup-vertical.svg) | Cabeçalhos de doc |
| Wordmark | [`web/static/assets/brand/callidus-wordmark.svg`](/web/static/assets/brand/callidus-wordmark.svg) | Só o nome "CALLIDUS" |
| Favicon | [`web/static/assets/brand/favicon.svg`](/web/static/assets/brand/favicon.svg) | Aba do navegador (`<link rel="icon">`) |

Os arquivos de origem (CorelDRAW) ficam em [`media/`](/media/) e são a fonte de verdade da marca. As
versões web em `web/static/assets/brand/` são geradas por
[`scripts/build_brand_assets.py`](/scripts/build_brand_assets.py) — rode o script depois de trocar
qualquer SVG em `media/`.

## Layout (v0.6)

| Zona | Função |
|------|--------|
| **Topbar** | Título da conversa, abas (Conversa · Acompanhamento · Provedores), controles do run, tema, painel de detalhes |
| **Sidebar** | Conversas e projetos, busca, novo projeto, saúde da API |
| **Conversa** | Bolhas do usuário e do agente, etapas, anexos, composer com provedor/modelo |
| **Inspetor** | Plano (árvore com filtros) e abas: detalhe, tentativas, testes, diff, contexto, métricas, grafo, ferramentas, linha do tempo |
| **Acompanhamento** | Estado da run em tempo real (mesmo redutor testado) |
| **Statusbar** | Estado do run, provedor/modelo em uso, versão |

## Tema

Claro e escuro, com o tema guardado em `localStorage` (`callidus-theme`) e aplicado no
`document.documentElement.dataset.theme`. As cores saem de tokens CSS (`--bg`, `--surface`,
`--accent`, …) — trocar a paleta é editar o bloco `:root` do `style.css`.

## Preferências

Persistidas em `localStorage` (`callidus-ui-v1`): último projeto, provider, modelo, tema.

## Regras de uso

- Só existe **uma execução por vez**: com envio em andamento ou run ativo, o composer não aceita
  novo pedido.
- O campo do composer é limpo **antes** de qualquer chamada à API; se a criação da tarefa falhar, o
  texto volta.
- Nenhuma credencial é exibida, copiada ou logada pela interface.

## Testes

```bash
pytest tests/test_web_frontend.py -v     # shell, módulos e contrato de rotas
node tests/web/observe-core.test.mjs     # redutor e renderizadores do acompanhamento
node tests/web/observe-stream.test.mjs   # stream SSE com reconexão
```

Voltar: [architecture/README.md](/docs/architecture/README.md)
