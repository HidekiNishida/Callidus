# Automação de sistema, desktop, engenharia e skills

Como o Callidus age no computador, no projeto e nas próprias skills.

Voltar: [Arquitetura](/docs/architecture/README.md) · Ferramentas: [ferramentas.md](/docs/architecture/ferramentas.md) · Skills: [skills-estrategia.md](/docs/architecture/skills-estrategia.md)

O agente não recebe um shell irrestrito. Cada ação passa pelo registro
([`registry.py`](/src/agent/tools/registry.py)): validação de argumentos, pré-requisitos,
política de risco, aprovação, cancelamento e prazo. O modelo vê um resumo curto; o detalhe
de uma ferramenta chega sob demanda por `tool_catalog` e `tool_help`.

## 📚 O que entra em cada etapa

Famílias extras (`system`, `desktop`, `engineering`, `skill`) só entram no prompt quando o
pedido cita a capacidade e a configuração não as desligou. O núcleo de arquivos e comandos
permanece. Configuração em [`Settings`](/src/agent/config.py):

| Campo | Efeito |
|-------|--------|
| `tool_enabled_families` | Lista fechada. Vazia significa todas. |
| `tool_disabled_families` | Famílias que não aparecem nem executam. |
| `tool_max_auto_risk` | Teto sem aprovação: `read`, `write`, `execute`, `configure`, `privileged`. Padrão: `write`. |
| `tool_always_allowed` / `tool_never_allowed` | Liberação ou bloqueio pontual, por id. |

`GET /tools/families`, `GET /tools/availability` e `GET /system/diagnose` expõem o mesmo
estado. A aba Ferramentas do inspetor resume diagnóstico, dependências ausentes e skills.

## 🔐 Política

Níveis, do mais seguro ao mais perigoso: leitura, escrita no workspace, execução de
comando ou aplicativo, configuração, ação privilegiada. Acima do teto, o registro devolve
`approval_required` e não executa. Família desligada ou regra `deny` devolve bloqueio.
Segredos em texto (`token=`, `password=`, chave privada) são redigidos antes do evento.

Argumentos são conferidos contra o esquema declarado — atalho (`path: str?`,
`command: str|list[str]`) ou JSON Schema das automações — antes do handler.

## 🖥️ Matriz de plataforma

Implementado significa que o adaptador existe e falha com diagnóstico quando a ferramenta
nativa falta. Testado neste ambiente significa executado em macOS (darwin) em 2026-10-21.
Windows e Linux não foram executados aqui.

| Capacidade | macOS | Windows | Linux | Testado aqui |
|------------|-------|---------|-------|--------------|
| Processos | `ps` | PowerShell | `ps` | sim (`list_processes`) |
| Abrir aplicativo | `open -a` | `cmd start` | `xdg-open` para arquivo/URL; lançar app não é universal | fluxo com processo Python local |
| Arquivo, URL, pasta | `open` | `start` | `xdg-open` | código do adaptador |
| Tela | Finder + `screencapture` | Windows Forms | `xrandr` no X11; Wayland explica a limitação | geometria lida |
| Captura | `screencapture -x` | `System.Drawing` | `gnome-screenshot` se existir | bloqueada: falta Screen Recording; a ferramenta diz a permissão |
| Janelas | `osascript` | processo com título | `wmctrl` no X11; Wayland não lista | estrutura conferida |
| Mouse e teclado | System Events | `user32` | `xdotool` no X11 | clique fora da tela é recusado sem injetar |
| Acessibilidade | System Events, elementos da janela | UI Automation | AT-SPI se `pyatspi` existir; senão diagnóstico | chamada real devolveu erro `-10000` e a instrução de Automação/Accessibility |
| Navegador | Playwright opcional; pesquisa HTTP sem ele | o mesmo | o mesmo | ações de página com página falsa; Chromium não foi exigido |

Não há automação headless universal. Desktop exige sessão gráfica. O agente não contorna
TCC, UAC nem portal: pede a permissão e para.

## 🛠️ Ferramentas por família

Sistema e comandos longos: `system_diagnose`, `list_processes`, `process_info`,
`kill_process`, `list_apps`, `launch_app`, `open_path`, `task_start`, `task_status`,
`task_cancel`, `list_env`, `system_resources`, `list_ports`, `check_dependencies`,
`download_file`, `file_hash`, `archive_files`, `extract_archive`, `http_request`.

Desktop: `desktop_screen`, `desktop_screenshot`, `desktop_windows`, `desktop_elements`,
`desktop_wait`, `desktop_click`, `desktop_click_element`, `desktop_drag`, `desktop_type`,
`desktop_key`, `desktop_scroll`. O clique por nome relê o retângulo na hora. Sem geometria,
não chuta coordenada.

Engenharia: `project_info`, `project_commands`, `read_manifest`, `git_branch`, `git_log`,
`run_check`, além de `git_status`, `git_diff`, `run_pytest` e `run_script` já existentes.

Navegador (`browser`, com `browser_mode` `headless` ou `visible`): `navigate`, `snapshot`,
`click`, `type`, `fill`, `press`, `scroll`, `screenshot`, `aria`, `console`, `network`,
`search`. Campo de senha não devolve o valor. Rede guarda método, URL e status, sem
cabeçalho. Playwright continua opcional.

## 🧩 Skills autorais

Pasta por skill, em `data/skills/<nome>/`: `SKILL.md`, `manifest.json` e, se precisar,
`scripts/`, `references/`, `assets/`, `tests/`.

Estados: `draft` na criação, `validated` quando o contrato passa, `approved` na ativação,
`disabled` na desativação. Instalação copia e registra proveniência; não executa script.
Remoção exige confirmação e guarda cópia. Atualização preserva a versão anterior para
`rollback`. Proposta de melhoria fica em arquivo próprio até ser aceita ou rejeitada; não
altera a skill sozinha.

Ferramentas: `skill_list`, `skill_search`, `skill_create`, `skill_validate`, `skill_test`,
`skill_install`, `skill_activate`, `skill_deactivate`, `skill_update`, `skill_history`,
`skill_propose`, `skill_resolve_proposal`.

## 🧪 Como testar

```bash
source .venv/bin/activate
python -m pytest -q tests/test_tool_contracts.py tests/test_tool_arguments.py \
  tests/test_system_automation.py tests/test_desktop_automation.py \
  tests/test_desktop_accessibility.py tests/test_engineering_tools.py \
  tests/test_skills_authoring.py tests/test_real_workflow_integration.py \
  tests/test_browser_actions.py tests/test_capability_exposure.py
node --test tests/web/tools-report.test.mjs
```

O fluxo de aplicativo, o de engenharia (descobrir, testar, relatar) e o de skill
(criar, validar, testar, usar) estão em `tests/test_real_workflow_integration.py`.
O aplicativo descartável é [`lab/demo_app.py`](/lab/demo_app.py).

## ⚖️ Decisões

| Decisão | Motivo |
|---------|--------|
| Adaptador por sistema, execução fora dele | O adaptador só monta o comando nativo; a política continua no registro. |
| Acessibilidade antes de coordenada | O retângulo é lido no momento da ação. Coordenada antiga não é reutilizada. |
| Visão computacional fora do caminho padrão | Modelos locais compactos não são obrigados a enxergar a tela. |
| Playwright direto, MCP opcional | Menos um processo para o fluxo local. MCP continua disponível à parte. |
| Skill não se concede permissão | Importar ou instalar não executa e não altera a política. |
