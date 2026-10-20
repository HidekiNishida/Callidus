"""
Arquivo: tests/test_resume.py
Nome: test_resume.py
Propósito: verificar o inventário de símbolos e o gancho de atualização usado pela ferramenta de sync do resume.md.
Responsabilidade: camada de testes — comportamento das funções de inventário e do gancho da ferramenta scripts/resume.py.
Componentes: símbolos de Python e de JavaScript, colapso de pastas no inventário, itens ausentes por seção, seções de arquivo, gancho silencioso e gancho que pede atualização.
Dependências: scripts/resume.py carregado por importlib, pytest.
Observações: a ferramenta é carregada diretamente do arquivo do repositório e nada é escrito em disco.
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("resume_tool", ROOT / "scripts" / "resume.py")
resume = importlib.util.module_from_spec(_spec)
sys.modules["resume_tool"] = resume
_spec.loader.exec_module(resume)


def test_python_symbols_keeps_classes_methods_and_signatures():
    """A extração de símbolos de Python guarda classes, métodos com assinatura, funções e assinaturas aninhadas."""
    source = (
        "class Box(Base):\n"
        "    def put(self, item: str, *, force=False) -> bool: ...\n"
        "async def fetch(url):\n    pass\n"
        "def outer():\n    def inner():\n        pass\n"
    )
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert keys == [
        "sym:src/x.py::Box(Base)",
        "sym:src/x.py::Box.put(item: str, *, force=False) -> bool",
        "sym:src/x.py::fetch(url)",
        "sym:src/x.py::outer()",
    ]


def test_python_symbols_ignores_syntax_errors():
    """Um arquivo com erro de sintaxe não produz símbolos."""
    assert resume.python_symbols("src/broken.py", "def (:") == []


def test_js_symbols_deduplicates_and_reads_params():
    """A extração de símbolos de JavaScript elimina duplicatas e lê os parâmetros."""
    source = "function a(x, y) {}\n  async function b() {}\nexport function a(z) {}\n"
    keys = [item.key for item in resume.js_symbols("web/app.js", source)]
    assert keys == ["sym:web/app.js::a(x, y)", "sym:web/app.js::b()"]


def test_inventory_collapses_folders_and_adds_parents():
    """O inventário agrupa os arquivos em pastas e inclui os diretórios pais."""
    items = resume.inventory(["media/icons/a.svg", "media/icons/b.svg", "src/agent/config.py"])
    keys = {item.key for item in items}
    assert "dir:media/" in keys and "dir:media/icons/" in keys
    assert not any(key.startswith("file:media/icons/") for key in keys)
    assert {"dir:src/", "dir:src/agent/", "file:src/agent/config.py"} <= keys
    assert any(key.startswith("sym:src/agent/config.py::Settings") for key in keys)


def test_missing_items_requires_symbol_inside_its_file_section():
    """Um símbolo só é considerado descrito se aparecer na seção do seu próprio arquivo."""
    items = [
        resume.Item("dir", "src/"),
        resume.Item("file", "src/a.py"),
        resume.Item("sym", "src/a.py", "Box.put", "(x)"),
        resume.Item("sym", "src/a.py", "run", "()"),
    ]
    text = (
        "## `src/`\n\n"
        "### `src/a.py`\n\n- `Box.put(x)` — guarda.\n\n"
        "### `src/b.py`\n\n- `run()` — está no arquivo errado.\n"
    )
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == ["sym:src/a.py::run()"]


def test_missing_items_does_not_accept_prefix_matches():
    """Um símbolo com nome parecido, mas diferente, não conta como descrito."""
    items = [resume.Item("file", "src/a.py"), resume.Item("sym", "src/a.py", "run", "()")]
    text = "### `src/a.py`\n\n- `run_all()` — outra função.\n"
    assert [item.name for item in resume.missing_items(items, text)] == ["run"]


def test_file_sections_include_deeper_headings_until_same_level():
    """A seção de um arquivo inclui os subtítulos mais profundos e para no título de mesmo nível."""
    text = "## `pasta/`\ntexto\n### `pasta/a.py`\n- `f()`\n## `outra/`\n"
    sections = resume.file_sections(text)
    assert "`pasta/a.py`" in sections["pasta/"]
    assert "outra" not in sections["pasta/"]


def test_hook_is_silent_when_turn_was_not_completed(monkeypatch, capsys):
    """Com o turno interrompido, o gancho não imprime nada."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"status": "aborted"})))
    assert resume.cmd_hook() == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_hook_asks_for_update_when_out_of_date(monkeypatch, capsys):
    """Com o inventário desatualizado, o gancho pede a atualização do resume.md."""
    stale = [resume.Item("sym", "src/a.py", "run", "()")]
    monkeypatch.setattr(resume, "report", lambda: (stale, ["sym:src/a.py::run()"], []))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"status": "completed"})))
    resume.cmd_hook()
    message = json.loads(capsys.readouterr().out)["followup_message"]
    assert "resume.md" in message and "sym:src/a.py::run()" in message
