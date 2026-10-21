"""
Arquivo: tests/test_capability_exposure.py
Nome: test_capability_exposure.py
Propósito: verificar a exposição de capacidades: quais ferramentas o modelo recebe e como o prompt as resume.
Responsabilidade: camada de testes — comportamento do catálogo de ferramentas e do resumo de capacidades.
Componentes: exposed_tools, capability_summary, families_for_objective, enabled_families.
Dependências: agent.tools.catalog, agent.tools.registry, pytest.
Observações: os testes verificam a regra de exposição, não a execução das ferramentas.
"""
import pytest

from agent.tools.catalog import (
    DISCOVERY_TOOLS,
    capability_summary,
    enabled_families,
    exposed_tools,
    families_for_objective,
)
from agent.tools.registry import build_default_registry


def test_pedido_de_sistema_expoe_a_familia_de_sistema():
    """Um pedido sobre processos expõe a família de sistema."""
    found = families_for_objective("encerre o processo que está travando o build")
    assert "system" in found


def test_pedido_de_desktop_expoe_a_familia_de_desktop():
    """Um pedido sobre tela e mouse expõe a família de desktop."""
    found = families_for_objective("tire um screenshot da janela e clique no botão")
    assert "desktop" in found


def test_pedido_de_engenharia_expoe_a_familia_de_engenharia():
    """Um pedido sobre testes e Git expõe a família de engenharia."""
    found = families_for_objective("roda os testes e olha o diff do git")
    assert "engineering" in found


def test_pedido_de_skill_expoe_a_familia_de_skill():
    """Um pedido sobre skills expõe a família de skills."""
    found = families_for_objective("crie uma skill para esse procedimento")
    assert "skill" in found


def test_pedido_neutro_nao_expoe_familias_extras():
    """Um pedido sem pista de capacidade não carrega ferramentas extras."""
    found = families_for_objective("ajuste a cor do botão do componente")
    assert found == set()


def test_exposicao_respeita_a_configuracao_de_familias():
    """Uma família desligada na configuração não entra na exposição."""
    reg = build_default_registry()

    class Settings:
        tool_enabled_families = ["system"]
        tool_disabled_families = []

    ids = exposed_tools(
        reg,
        objective="encerre o processo travado",
        base=("read_file",),
        settings=Settings(),
    )
    assert "kill_process" in ids
    assert "desktop_click" not in ids
    assert "read_file" in ids


def test_exposicao_nunca_esvazia_o_nucleo():
    """As ferramentas do núcleo e as de descoberta estão sempre presentes."""
    reg = build_default_registry()
    ids = exposed_tools(reg, objective="ajuste a cor do botão", base=("read_file", "write_file"))
    assert "read_file" in ids
    assert "write_file" in ids
    for tool_id in DISCOVERY_TOOLS:
        assert tool_id in ids


def test_resumo_de_capacidades_e_compacto():
    """O resumo lista uma linha por família, não uma linha por ferramenta."""
    reg = build_default_registry()
    ids = exposed_tools(
        reg,
        objective="encerre o processo e tire um screenshot da janela",
        base=("read_file",),
    )
    summary = capability_summary(reg, ids)
    assert summary
    assert "sistema" in summary
    assert "desktop" in summary
    assert len(summary.splitlines()) <= 4


def test_familias_desligadas_por_configuracao_removem_a_exposicao():
    """Com a família de desktop desligada, o pedido de desktop não expõe nada dela."""
    reg = build_default_registry()

    class Settings:
        tool_enabled_families = []
        tool_disabled_families = ["desktop"]

    enabled = enabled_families(Settings())
    assert enabled is not None
    assert "desktop" not in enabled
    assert "system" in enabled
    assert "file" in enabled
    ids = exposed_tools(
        reg,
        objective="clique no botão da janela",
        base=("read_file",),
        settings=Settings(),
    )
    assert "desktop_click" not in ids
