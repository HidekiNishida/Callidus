"""
Arquivo: tests/test_desktop_automation.py
Nome: test_desktop_automation.py
Propósito: verificar a automação de desktop: adaptadores por plataforma, tela, entrada e janelas.
Responsabilidade: camada de testes — comportamento observável da camada de desktop no sistema atual.
Componentes: adaptadores por sistema operacional, screen_info, click, list_windows.
Dependências: agent.desktop, agent.system.adapters, agent.tools.registry, pytest.
Observações: as ações que dependem de permissão do sistema são verificadas pelo código de retorno, não por efeito.
"""
import platform

import pytest

from agent.desktop.capabilities import screen_info
from agent.desktop.input import click
from agent.desktop.windows import list_windows
from agent.system.adapters import MacAdapter, SystemAdapter, WindowsAdapter, current_os, get_adapter, session_kind
from agent.tools.registry import ToolContext, build_default_registry


def test_adaptador_corresponde_ao_sistema_operacional():
    """Cada plataforma conhecida tem um adaptador próprio com comandos declarados."""
    system = current_os()
    adapter = get_adapter()
    assert adapter.name == system
    if system == "macos":
        assert isinstance(adapter, MacAdapter)
        assert adapter.launch_cmd[:2] == ("open", "-a")
    elif system == "windows":
        assert isinstance(adapter, WindowsAdapter)
        assert "powershell" in adapter.launch_cmd
    else:
        assert adapter.name == "linux"


def test_plataforma_desconhecida_cai_no_adaptador_generico():
    """Uma plataforma sem adaptador específico devolve o genérico, com nota de limitação."""
    adapter = get_adapter("plan9")
    assert isinstance(adapter, SystemAdapter)
    assert adapter.notes


def test_sessao_grafica_e_reconhecida():
    """A natureza da sessão é sempre classificada."""
    assert session_kind() in {"aqua", "windows", "x11", "wayland", "headless"}


def test_informacoes_de_tela_traz_limites_ou_explicacao():
    """A tela informa a geometria quando consegue, e explica quando não consegue."""
    info = screen_info()
    assert "bounds" in info
    assert "session" in info or "notes" in info
    if not info.get("success"):
        assert info.get("error")


def test_clique_fora_da_tela_e_recusado_quando_a_geometria_e_conhecida():
    """Um ponto fora da tela conhecida é recusado antes de tocar o sistema."""
    info = screen_info()
    bounds = info.get("bounds")
    if not bounds:
        pytest.skip("geometria da tela indisponível neste ambiente")
    out = click(bounds["x"] + bounds["width"] + 500, bounds["y"] + bounds["height"] + 500)
    assert out["success"] is False
    assert "fora da tela" in out["error"]


def test_janelas_devolve_estrutura_mesmo_sem_permissao():
    """A enumeração de janelas devolve a estrutura, com a limitação quando falta permissão."""
    out = list_windows()
    assert "windows" in out
    assert "count" in out
    if not out.get("success"):
        assert out.get("error")


@pytest.mark.asyncio
async def test_ferramenta_de_desktop_exige_sessao_grafica(tmp_path):
    """A captura só funciona com sessão gráfica e permissão de gravação; o bloqueio é explicado."""
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))
    out = await reg.execute("desktop_screenshot", ctx, {})
    if session_kind() == "headless":
        assert out["success"] is False
        assert "requisitos ausentes" in out["error"]
    elif out["success"]:
        assert out["bytes"] > 0
    else:
        # Permissão do sistema (Screen Recording) negada: a ferramenta diz o que falta.
        assert out["error"]
        assert out.get("hint")


@pytest.mark.asyncio
async def test_ferramenta_de_janelas_e_declarada_como_leitura(tmp_path):
    """A ferramenta de janelas é de leitura e não exige aprovação."""
    reg = build_default_registry()
    spec = reg.get_spec("desktop_windows")
    assert spec.risk == "read"
    assert spec.requires_approval is False
    assert spec.family == "desktop"


def test_plataforma_de_teste_esta_declarada():
    """O teste roda em um sistema operacional conhecido pelo projeto."""
    assert platform.system().lower() in {"darwin", "windows", "linux"}
