# tests/test_web_frontend.py — a interface Vue está montada e conversa com rotas que existem
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.api.main import app


def _all_paths(router) -> set[str]:
    """Rotas da API, incluindo as de routers incluídos (o FastAPI mantém aninhadas)."""
    paths: set[str] = set()
    for route in router.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            paths |= _all_paths(original)
    return paths


WEB = Path(__file__).resolve().parents[1] / "web" / "static"
APP_DIR = WEB / "assets" / "app"


def _html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


def test_index_mounts_the_vue_application():
    html = _html()
    assert '<div id="app">' in html
    assert "/assets/vendor/vue.global.prod.js" in html
    assert "/assets/app/main.js" in html
    assert "/assets/app/style.css" in html
    # O shell não carrega mais o front antigo em JS puro.
    assert "assets/app.js" not in html
    assert "observe.js" not in html


def test_vue_is_vendored_locally():
    vendor = WEB / "assets" / "vendor" / "vue.global.prod.js"
    assert vendor.is_file()
    content = vendor.read_text(encoding="utf-8")
    assert "vue v3" in content
    assert len(content) > 50_000


@pytest.mark.parametrize(
    "module",
    [
        "main.js",
        "store.js",
        "api.js",
        "ui.js",
        "components/sidebar.js",
        "components/topbar.js",
        "components/chat.js",
        "components/details.js",
        "components/providers.js",
        "components/live.js",
        "components/palette.js",
        "components/settings.js",
    ],
)
def test_application_modules_exist(module):
    assert (APP_DIR / module).is_file()


def test_frontend_uses_endpoints_that_exist():
    """Cada rota chamada pela interface precisa existir na API (contrato front ↔ back)."""
    routes = {re.sub(r"\{[^}]+\}", "*", path) for path in _all_paths(app)}
    prefixes: set[str] = set()
    for path in APP_DIR.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"api\(\s*[`\"'](/[^`\"'$]*)", text):
            raw = match.group(1)
            raw = raw.split("${")[0].rstrip("/$")
            if raw:
                prefixes.add(raw)
    family = (
        "/projects",
        "/conversations",
        "/tasks",
        "/runs",
        "/providers",
        "/config",
        "/fs",
        "/mcp",
        "/tools",
        "/health",
    )
    checked = {prefix for prefix in prefixes if prefix.startswith(family)}
    assert checked, "a interface deveria chamar alguma rota da API"
    for prefix in checked:
        assert any(candidate.startswith(prefix) for candidate in routes), (
            f"rota usada pela interface não existe: {prefix}"
        )


def test_interface_exposes_project_management():
    """A interface precisa conseguir criar, renomear e remover projetos."""
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    for action in ("deleteProject", "renameProject", "moveProject"):
        assert f"export async function {action}" in store, action
    assert 'api(`/projects/${project.id}`, { method: "DELETE" })' in store
    routes = _all_paths(app)
    assert "/projects/{project_id}" in routes


def test_interface_has_command_palette_and_settings():
    """Paleta de comandos (⌘K) e tela de ajustes existem e estão ligados."""
    palette = (APP_DIR / "components" / "palette.js").read_text(encoding="utf-8")
    settings = (APP_DIR / "components" / "settings.js").read_text(encoding="utf-8")
    main = (APP_DIR / "main.js").read_text(encoding="utf-8")
    assert "state.paletteOpen" in palette
    assert "key.toLowerCase() === \"k\"" in main
    assert "watchViewport" in main
    for tab in ("geral", "execucao", "projetos", "atalhos"):
        assert f'id: "{tab}"' in settings


def test_stylesheet_declares_responsive_and_motion_rules():
    css = (APP_DIR / "style.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
    assert "pointer: coarse" in css
    assert "max-width: 899px" in css
    assert "max-width: 1179px" in css
    assert "bottom-nav" in css
    assert "--dur-" in css


def test_atividade_do_chat_e_traduzida_para_portugues():
    """O feed ao vivo mostra ferramentas, comandos e arquivos em português."""
    ui = (APP_DIR / "ui.js").read_text(encoding="utf-8")
    for label in ("Leitura de arquivo", "Escrita de arquivo", "Comando", "Testes", "Listagem de pasta"):
        assert label in ui, label
    assert "describeActivity" in ui
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    assert "activity" in chat
    assert "pause-banner" in chat
    assert "resumeRun" in chat
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    assert "pushActivity" in store
    assert "resumeRun" in store


def test_chat_mostra_diffs_e_detalhes_recolhiveis():
    """Edições aparecem em tempo real, com animação e opção de recolher/abrir."""
    ui = (APP_DIR / "ui.js").read_text(encoding="utf-8")
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    css = (APP_DIR / "style.css").read_text(encoding="utf-8")
    # o tradutor sabe extrair o diff do evento de arquivo
    assert "diff:" in ui and "diffLines" in ui and "summarizeActivity" in ui
    # a tela do chat tem o diff, o botão de recolher e a transição de abertura
    assert "activity-diff" in chat
    assert "activity-collapse" in chat
    assert "abrir detalhes" in chat and "recolher" in chat
    assert 'name="expand"' in chat
    assert "TransitionGroup" in chat
    # estilo das linhas de diff e da animação
    assert ".activity-diff .diff-add" in css
    assert ".activity-diff .diff-del" in css
    assert ".expand-enter-active" in css


def test_stream_e_fechado_pela_api_correta():
    """`createStream` expõe `stop`; a interface precisa usar esse nome (usar `close` derrubava a
    conexão da mensagem seguinte e a segunda mensagem nunca era respondida)."""
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    stream_mod = (APP_DIR / "live-stream.js").read_text(encoding="utf-8")
    assert "return { stop, get source()" in stream_mod
    assert "typeof stream.stop === \"function\"" in store
    assert "stream?.close()" not in store


def test_atividade_fica_por_mensagem_e_os_detalhes_seguem_a_selecao():
    """Cada mensagem tem a sua atividade e o painel de detalhes acompanha a seleção."""
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    assert "state.feeds[root.id]" in chat
    assert "rootIdOf" in store
    assert "await selectTask(task.id)" in store
    # resposta obsoleta do inspetor não sobrescreve a tarefa atual
    assert "inspectorToken" in store


def test_mensagem_enviada_durante_a_execucao_entra_na_fila():
    """Enviar durante a execução agenda a mensagem (antes ela se perdia)."""
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    assert "state.queued" in store
    assert "flushQueue" in store
    assert "Mensagem agendada" in chat
    assert "cancelQueued" in store


def test_rolagem_automatica_para_quando_o_usuario_esta_no_fim():
    """A rolagem acompanha o feed só enquanto o usuário estiver no fim da conversa."""
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    assert "const stick = atBottom.value && !userTookOver.value;" in chat
    assert "behavior: \"smooth\"" in chat
    assert "scrollHeight" in chat
    assert "@scroll=\"onScroll\"" in chat
    # o usuário assume o controle (roda/toque) e a rolagem suave em andamento é cancelada
    assert "onUserScrollIntent" in chat
    assert "userTookOver" in chat


def test_etiquetas_do_plano_acima_do_prompt():
    """As tarefas do plano viram etiquetas fixas acima do campo de envio (estilo Kilo)."""
    chat = (APP_DIR / "components" / "chat.js").read_text(encoding="utf-8")
    css = (APP_DIR / "style.css").read_text(encoding="utf-8")
    assert "plan-strip" in chat
    assert "plan-tag" in chat
    assert "planTags" in chat
    # concluídas somem, em aberto ficam
    assert "COMPLETED" in chat
    # rolagem horizontal quando há muitas etiquetas
    assert ".plan-strip-inner" in css and "overflow-x: auto" in css


def test_painel_de_execucao_tem_interacoes():
    """O painel de execução responde: filtros, árvore, diff e seleção de tarefa."""
    live = (APP_DIR / "components" / "live.js").read_text(encoding="utf-8")
    css = (APP_DIR / "style.css").read_text(encoding="utf-8")
    for hook in ("data-obs-cat", "data-obs-errors", "data-obs-toggle", "data-obs-task", "data-obs-file"):
        assert hook in live, hook
    assert "renderFilters" in live and "renderTree" in live and "renderFiles" in live
    # estilos do redutor (a classe `obs-` nunca teve estilo na interface nova)
    assert ".obs-node" in css and ".obs-chip" in css and ".obs-diff" in css


def test_markdown_da_resposta_final_e_completo():
    """A resposta final é formatada: títulos, listas aninhadas, tabelas, código e citações."""
    ui = (APP_DIR / "ui.js").read_text(encoding="utf-8")
    for feature in ("md-table", "blockquote", "md-code", "renderList", "isTableSeparator", "inline("):
        assert feature in ui, feature
    assert "escapeHtml" in ui


def test_execucao_automatica_continua_o_run():
    """O modo automático faz o servidor conduzir os passos (a execução não para no 1º passo)."""
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    topbar = (APP_DIR / "components" / "topbar.js").read_text(encoding="utf-8")
    assert "autoMode" in store
    assert "if (state.autoMode)" in store
    assert "void autoRun();" in store
    assert "setAutoMode" in topbar


def test_interface_tem_seletor_de_pasta_com_criacao():
    main = (APP_DIR / "main.js").read_text(encoding="utf-8")
    assert "pickFolderForProject" in main
    assert "createFolder" in main
    assert "/fs/mkdir" in main


def test_interface_tem_configuracao_de_computador_remoto():
    main = (APP_DIR / "main.js").read_text(encoding="utf-8")
    store = (APP_DIR / "store.js").read_text(encoding="utf-8")
    settings = (APP_DIR / "components" / "settings.js").read_text(encoding="utf-8")
    assert "/remote" in store
    assert "saveRemote" in store and "testRemote" in store and "clearRemote" in store
    assert "Computador remoto" in settings
    assert 'v-model="modal.remote.shell"' in main
    routes = _all_paths(app)
    assert "/projects/{project_id}/remote" in routes
    assert "/projects/{project_id}/remote/test" in routes
    assert "/fs/mkdir" in routes


def test_providers_view_uses_the_configuration_endpoints():
    text = (APP_DIR / "store.js").read_text(encoding="utf-8")
    assert "/providers/config" in text
    assert "/providers/" in text
    routes = _all_paths(app)
    assert "/providers/config" in routes
    assert "/providers/config/{name}/secret" in routes
