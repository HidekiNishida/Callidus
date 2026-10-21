"""
Arquivo: tests/test_desktop_accessibility.py
Nome: test_desktop_accessibility.py
Propósito: verificar a leitura da árvore de acessibilidade e a recusa de clique sem geometria.
Responsabilidade: camada de testes — interpretação do texto nativo e contratos das ferramentas.
Componentes: parse_accessibility_text, match_elements, element_center, list_elements, click_named.
Dependências: agent.desktop.accessibility, agent.tools.registry, pytest.
Observações: o clique real não é disparado; o teste do ambiente só confere a estrutura da resposta.
"""
import pytest

from agent.desktop.accessibility import (
    click_named,
    element_center,
    list_elements,
    match_elements,
    parse_accessibility_text,
)
from agent.tools.registry import build_default_registry


def test_interpreta_janela_e_elemento_com_retangulo():
    """O texto do adaptador vira janela, papel e geometria."""
    parsed = parse_accessibility_text(
        "WINDOW|Bloco de Notas|TextEdit\nSalvar||AXButton||10||20||80||24\n"
    )
    assert parsed["success"] is True
    assert parsed["window"] == "Bloco de Notas"
    assert parsed["count"] == 1
    assert parsed["elements"][0]["role"] == "AXButton"
    assert element_center(parsed["elements"][0]) == (50, 32)


def test_elemento_sem_area_nao_tem_centro():
    """Retângulo vazio não produz coordenada."""
    assert element_center({"bounds": {"x": 1, "y": 2, "width": 0, "height": 10}}) is None


def test_nome_de_aplicativo_invalido_e_recusado():
    """Aspas e caracteres de script não entram no comando nativo."""
    out = list_elements('Finder"; say "oi')
    assert out["success"] is False
    assert "inválido" in out["error"]


def test_clique_sem_nome_nao_toca_a_interface():
    """Sem nome, a função devolve erro antes de consultar a tela."""
    out = click_named("  ")
    assert out["success"] is False
    assert "nome" in out["error"]


def test_casamento_ignora_maiusculas():
    """O nome pedido casa como trecho, sem diferenciar maiúsculas."""
    found = match_elements([{"name": "Botão Salvar"}, {"name": "Fechar"}], "salvar")
    assert len(found) == 1


def test_janela_ausente_e_um_resultado_vazio():
    """Aplicativo sem janela não é tratado como falha de parse."""
    parsed = parse_accessibility_text("NOWINDOW|Finder")
    assert parsed["success"] is True
    assert parsed["count"] == 0
    assert parsed["application"] == "Finder"


def test_ferramentas_de_acessibilidade_estao_no_registro():
    """Leitura não pede aprovação; o clique no elemento pede."""
    registry = build_default_registry()
    reading = registry.get_spec("desktop_elements")
    clicking = registry.get_spec("desktop_click_element")
    assert reading.risk == "read"
    assert reading.requires_approval is False
    assert clicking.requires_approval is True
    assert "name" in clicking.input_schema


@pytest.mark.asyncio
async def test_listagem_real_devolve_estrutura():
    """No sistema atual, a listagem devolve elementos ou explica a limitação."""
    out = list_elements(limit=5)
    assert "elements" in out
    assert "count" in out
    if not out.get("success"):
        assert out.get("error")
