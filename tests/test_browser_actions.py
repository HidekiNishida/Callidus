"""
Arquivo: tests/test_browser_actions.py
Nome: test_browser_actions.py
Propósito: verificar as ações de página que não dependem de um navegador real.
Responsabilidade: camada de testes — preenchimento, captura, árvore acessível, console e rede.
Componentes: _act.
Dependências: agent.tools.browser, pytest.
Observações: a página é falsa; o teste prova o contrato da ação, não o Chromium.
"""
from pathlib import Path

from agent.tools.browser import _act


class _Locator:
    """Localizador falso: `first` aponta para ele mesmo e grava o texto preenchido."""

    def __init__(self) -> None:
        self.filled = None

    @property
    def first(self):
        """O primeiro casamento, que neste dublê é o próprio localizador."""
        return self

    def fill(self, value: str, timeout: int = 0) -> None:
        """Grava o texto que seria digitado no campo."""
        self.filled = value

    def aria_snapshot(self) -> str:
        """Árvore acessível mínima."""
        return "- button Salvar"


class _Page:
    """Página falsa com URL, título e localizador."""

    def __init__(self, path: Path) -> None:
        self.url = "https://exemplo.dev/login"
        self.path = path
        self.locator_used = ""

    def title(self) -> str:
        """Título fixo da página."""
        return "Login"

    def locator(self, selector: str) -> _Locator:
        """Devolve o localizador e guarda o seletor pedido."""
        self.locator_used = selector
        locator = _Locator()
        self._locator = locator
        return locator

    def screenshot(self, path: str, full_page: bool = False) -> None:
        """Grava bytes no caminho pedido para a ação medir o tamanho."""
        Path(path).write_bytes(b"png-falso")


def test_preenchimento_de_senha_nao_devolve_o_valor():
    """O resultado informa que o campo foi preenchido, sem o segredo."""
    page = _Page(Path("."))
    out = _act(page, "fill", {"selector": "#password", "text": "segredo"}, headed=False)
    assert out["success"] is True
    assert out["filled"] == "[REDACTED]"
    assert "segredo" not in str(out)


def test_captura_grava_o_arquivo_e_informa_o_tamanho(tmp_path: Path):
    """A captura devolve o caminho e a quantidade de bytes, não a imagem no texto."""
    target = tmp_path / "pagina.png"
    page = _Page(target)
    out = _act(page, "screenshot", {"path": str(target)}, headed=False)
    assert out["success"] is True
    assert out["bytes"] == len(b"png-falso")
    assert target.is_file()


def test_arvore_acessivel_e_console_e_rede():
    """Ária, console e rede saem estruturados e a ação desconhecida é recusada."""
    page = _Page(Path("."))
    aria = _act(page, "aria", {}, headed=True)
    assert aria["success"] is True
    assert "Salvar" in aria["aria"]
    assert aria["mode"] == "visible"
    console = _act(page, "console", {}, headed=False, console_log=[{"type": "error", "text": "falhou"}])
    assert console["messages"][0]["type"] == "error"
    network = _act(page, "network", {}, headed=False, network_log=[{"method": "GET", "url": "https://exemplo.dev", "status": 200}])
    assert network["requests"][0]["status"] == 200
    unknown = _act(page, "explodir", {}, headed=False)
    assert unknown["success"] is False
