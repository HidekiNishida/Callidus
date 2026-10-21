# Interface web

A SPA: streaming de eventos, estado da interface e comunicação com a API.

<p align="center">
  <img src="/web/static/assets/brand/callidus-wordmark.svg" alt="Callidus" width="300" />
</p>

Estáticos em [`web/static/`](/web/static/) · Análise UX: [ux-ui.md](/docs/architecture/ux-ui.md)

A interface é uma **SPA em Vue 3** (build global versionado localmente, sem etapa de build),
servida pela API em `/`. Ela conversa só com a API HTTP — nenhuma regra de negócio no navegador.

## 🏗️ Arquitetura

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
| [`assets/app/components/`](/web/static/assets/app/components/) | `sidebar`, `topbar`, `chat`, `details`, `live`, `providers`, `settings`, `palette` |
| [`assets/app/style.css`](/web/static/assets/app/style.css) | Sistema visual: tokens, tema claro/escuro, componentes |

O redutor (`live-state.js`) e os renderizadores (`live-view.js`) são os mesmos testados pelo Node
([`tests/web/`](/tests/web/)) — o painel de acompanhamento não tem lógica duplicada.

## 💡 Telas

| Tela | Onde | O que faz |
|------|------|-----------|
| **Conversa** | Aba na topbar (ou barra inferior no celular) | Chat com o agente, etapas da execução, anexos, escolha de provedor/modelo/navegador e controles do run |
| **Acompanhamento** | Aba na topbar (habilitada com run ativo) | Plano da execução, chamadas ao modelo em streaming, arquivos, verificações, atividade e métricas |
| **Provedores** | Aba na topbar | Configuração de provedores: criar, editar, testar conexão, listar modelos, definir o padrão, gravar/apagar credencial |
| **Ajustes** | Aba “Ajustes” / barra inferior | Aparência (tema, densidade), padrões de execução, **gerência de projetos** (renomear, trocar pasta, remover) e atalhos |
| **Paleta de comandos** | `⌘K` / `Ctrl+K` | Busca de comandos: navegar, executar, alternar tema, renomear/apagar conversa, remover projeto |

### Atividade em tempo real no chat

Dentro da bolha do agente, o que o agente está fazendo aparece em tempo real, em português:

| Evento | O que aparece |
|--------|---------------|
| Pensamento do agente | “Pensando na alteração «X»…” |
| Chamada de modelo | “Chamando o modelo llama3.2” + se a resposta vem em fragmentos |
| Resposta do modelo | “Resposta do modelo (312 caracteres)” + chamadas de ferramenta |
| Ferramenta | “Leitura de arquivo”, “Escrita de arquivo”, “Listagem de pasta”… com o caminho |
| Comando | “Comando” + o comando e a **saída em tempo real** |
| Testes | “Testes” + contagem de aprovados/falhos |
| Arquivos | “Leu/Alterou/Removeu arquivo” + **diff** (linhas `+`/`−` coloridas) |

Cada linha entra com animação, o ícone mostra o estado (em andamento, concluído, falhou) e o tempo
de execução quando existe. A tradução está em [`ui.js`](/web/static/assets/app/ui.js)
(`TOOL_LABEL`, `describeActivity`, `summarizeActivity` e `diffLines`).

**Recolher e abrir detalhes**: o cabeçalho do bloco resume o turno (“2 escrita(s) · 1 comando(s) ·
1 teste(s)”) e tem o botão **recolher** (esconde tudo) / **abrir detalhes**. Cada linha tem uma
chevron: clicar abre o que foi feito (caminho, comando, saída, diff, contagens) com animação de
altura. Edições de arquivo já abrem com o diff visível.

**Execução automática**: o botão **Auto** da topbar liga/desliga o modo em que o servidor conduz
os passos até o fim (padrão: ligado). Sem ele, a execução parava no primeiro passo — a interface
mostrava a tela “travada”.

**Uma mensagem por vez, sem perder nada**: enviar durante uma execução não é bloqueado — a
mensagem fica **agendada** (aparece o aviso “Mensagem agendada: …”, com opção de cancelar) e entra
assim que a execução atual termina.

**Atividade por mensagem**: cada mensagem guarda a sua própria atividade (o feed é separado por
tarefa raiz), então a segunda mensagem não herda o que aconteceu na primeira. O evento
`work.explained` entra na narrativa da bolha (o que o Callidus está fazendo), separada da
resposta final e da lista de ferramentas e chamadas do modelo. Ao reconectar, o histórico
persistido da run é recolocado nesse feed, sem duplicar o mesmo evento. O painel de
detalhes acompanha a tarefa selecionada e ignora respostas antigas que chegam fora de ordem.

**Rolagem automática**: a conversa acompanha o feed **enquanto a rolagem da conversa estiver no
ponto mais baixo**. Se o usuário sobe para ler (roda do mouse, toque ou teclado), a rolagem
automática para — e volta a acompanhar assim que ele retorna ao fim. O scroll gerado pela própria
rolagem automática não conta como decisão do usuário (uma flag evita que a posição “falso” de
rolando interrompa o acompanhamento).

**Etiquetas do plano (só acima do prompt)**: as tarefas em aberto do plano atual viram etiquetas
fixas acima do campo de envio (estilo Kilo) — e **não** aparecem dentro da bolha da mensagem.
Elas acompanham o planejamento: mudam de estado (concluída, em execução, bloqueada), somem quando a
tarefa é concluída e podem ser clicadas para abrir os detalhes da tarefa. Quando há muitas, a faixa
rola na horizontal. A faixa aparece **enquanto a execução da mensagem está em curso**: com a run
pausada ou terminada, nada fica parado na tela.

**Painel de execução (“Acompanhamento”)**: mostra o cabeçalho da run (situação, progresso,
conexão), a barra de filtros (categoria, só falhas, busca por texto), a árvore de tarefas com
contadores e evidências, as chamadas ao modelo, os arquivos alterados (com o diff expansível), as
verificações, as ferramentas, a atividade e as métricas. Todas as interações funcionam dentro da
interface: expandir a árvore, alternar filtros, filtrar por texto, abrir o diff e selecionar a
tarefa (que abre os detalhes ao lado).

**Resposta final em markdown**: títulos, ênfase, código, listas (com aninhamento), tabelas,
citações, linhas horizontais, links e imagens — o HTML do modelo é escapado antes de qualquer
marcação.

## 💡 Layout responsivo

A interface se adapta em três faixas, sem esconder função essencial:

| Faixa | Largura | Comportamento |
|-------|---------|---------------|
| **Desktop** | ≥ 1180 px | Três colunas: barra lateral · conversa · painel de detalhes (fixo) |
| **Tablet** | 900–1179 px | Barra lateral vira **gaveta** (botão no topo, `⌘B`); detalhes viram painel sobreposto à direita; abas da topbar viram só ícones |
| **Celular** | < 900 px | Coluna única, **barra de navegação inferior** (Conversa · Execução · Provedores · Ajustes), detalhes em **folha inferior**, controles de execução na barra de contexto e alvos de toque de 40–56 px |

Regras de toque (Material/HIG aplicadas): alvo mínimo de 40–44 px, folga de 8 px entre alvos, nenhuma ação depende de *hover*, navegação principal na zona do polegar (barra inferior), `safe-area-inset-bottom` respeitada e tipografia mínima de 15 px no campo de texto.

## 💡 Movimento

Tokens de motion no `style.css` (`--dur-1` a `--dur-4`, `--ease`, `--ease-out`, `--spring`) e animações
em todas as interações:

| Interação | Movimento |
|-----------|-----------|
| Troca de tela | Fade + deslocamento de 8 px (`<Transition name="view">`) |
| Gaveta lateral / folha inferior | Deslize horizontal/vertical com `cubic-bezier` próprio |
| Entrada de mensagens e etapas | Fade + subida escalonada |
| Paleta de comandos | Escala 0.97 → 1 com mola (`--spring`) |
| Avisos (toasts) | Deslize lateral + saída animada (`TransitionGroup`) |
| Botões e chips | Escala 0.92 no toque, brilho no hover |
| Ponto de status “working” | Pulso contínuo |
| Estado vazio / carregando | Fade e spinner |

`prefers-reduced-motion: reduce` desliga todas as animações e transições.

## ⚙️ Configuração de provedores pela interface

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

## 💡 Identidade visual (Callidus)

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

## 💡 Layout (v0.6)

| Zona | Função |
|------|--------|
| **Topbar** | Título da conversa, abas (Conversa · Acompanhamento · Provedores), controles do run, tema, painel de detalhes |
| **Sidebar** | Conversas e projetos, busca, novo projeto, saúde da API |
| **Conversa** | Bolhas do usuário e do agente, etapas, anexos, composer com provedor/modelo |
| **Inspetor** | Plano (árvore com filtros) e abas: detalhe, tentativas, testes, diff, contexto, métricas, grafo, ferramentas (diagnóstico, dependências ausentes e skills), linha do tempo |
| **Acompanhamento** | Estado da run em tempo real (mesmo redutor testado) |
| **Statusbar** | Estado do run, provedor/modelo em uso, versão |

## ⚙️ Tema

Claro e escuro, com o tema guardado em `localStorage` (`callidus-theme`) e aplicado no
`document.documentElement.dataset.theme`. As cores saem de tokens CSS (`--bg`, `--surface`,
`--accent`, …) — trocar a paleta é editar o bloco `:root` do `style.css`.

## 🧠 Gerência de projetos

A interface permite configurar tudo o que é ajustável sem editar arquivo:

- **Projetos** (Ajustes → Projetos, ou o botão de lixeira na barra lateral): renomear, trocar a
  pasta (pelo seletor de pastas, com queda para a pasta do usuário quando o caminho está fora do
  alcance da navegação), **criar pasta** (botão no seletor, `POST /fs/mkdir`) e **remover**. A remoção apaga conversas, tarefas, execuções, memória e o
  grafo do projeto pela API (`DELETE /projects/{id}`) — **os arquivos da pasta não são apagados**,
  e a confirmação deixa isso explícito.
- **Provedores** (aba Provedores): provedores nomeados, credencial, timeout, cabeçalhos e padrão.
- **Execução** (Ajustes → Execução): provedor, modelo, navegador e permissão de ferramentas.
- **Computador remoto** (Ajustes → Projetos → ícone de servidor): host, porta, usuário, chave
  SSH, pasta do projeto no servidor e sistema (Linux/macOS ou Windows/PowerShell). Com isso, os
  comandos, leituras, escritas e listagens do projeto passam a rodar no servidor por SSH
  (`src/agent/remote/`). O botão **Testar conexão** confirma o acesso antes de salvar.
- **Aparência** (Ajustes → Geral): tema claro/escuro e densidade.

## ⚙️ Preferências

Persistidas em `localStorage`: `callidus-ui-v1` (projeto, provedor, modelo), `callidus-theme` e
`callidus-density`.

## 🗺️ Regras de uso

- Só existe **uma execução por vez**: com envio em andamento ou run ativo, o composer não aceita
  novo pedido.
- O campo do composer é limpo **antes** de qualquer chamada à API; se a criação da tarefa falhar, o
  texto volta.
- Nenhuma credencial é exibida, copiada ou logada pela interface.

## 🧪 Testes

```bash
pytest tests/test_web_frontend.py -v     # shell, módulos, rotas, responsivo e motion
pytest tests/test_project_delete.py -v    # remoção de projeto em cascata
node tests/web/observe-core.test.mjs     # redutor e renderizadores do acompanhamento
node tests/web/observe-stream.test.mjs   # stream SSE com reconexão
```

A checagem visual (desktop, tablet e celular) é feita com Playwright/Chromium em headed ou
headless: `python -m playwright` não é dependência da suíte — o teste de interface roda por
inspeção manual e pelos contratos automatizados acima.

Voltar: [architecture/README.md](/docs/architecture/README.md)