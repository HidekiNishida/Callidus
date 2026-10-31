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


def test_python_symbols_async_function_with_return():
    """Função assíncrona com parâmetros e tipo de retorno é extraída corretamente."""
    source = "async def fetch(url: str, *, timeout: float = 5.0) -> dict[str, Any]:\n    pass\n"
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert any("fetch(url: str, *, timeout: float" in k and "-> dict[str, Any]" in k for k in keys)


def test_python_symbols_pydantic_base_model():
    """Classe que herda de BaseModel é extraída como classe com bases."""
    source = "class User(BaseModel):\n    name: str\n    email: str\n"
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::User(BaseModel)" in keys


def test_python_symbols_dataclass():
    """Dataclass é extraída como classe."""
    source = "@dataclass\nclass Point:\n    x: int\n    y: int\n"
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::Point" in keys


def test_python_symbols_enum():
    """Enum é extraída como classe."""
    source = "class Status(str, Enum):\n    ACTIVE = 'active'\n    INACTIVE = 'inactive'\n"
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::Status(str, Enum)" in keys


def test_python_symbols_two_classes_with_homonym_methods():
    """Duas classes com métodos de mesmo nome geram chaves distintas."""
    source = (
        "class A:\n    def process(self) -> None: ...\n"
        "class B:\n    def process(self, x: int) -> str: ...\n"
    )
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::A.process() -> None" in keys
    assert "sym:src/x.py::B.process(x: int) -> str" in keys


def test_python_symbols_union_type_none():
    """União de tipos com `str | None` é preservada na assinatura."""
    source = "def get_name(user_id: int) -> str | None:\n    pass\n"
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::get_name(user_id: int) -> str | None" in keys


def test_python_symbols_decorated_method():
    """Método decorado é extraído (o decorador não entra na assinatura)."""
    source = (
        "class Service:\n"
        "    @classmethod\n"
        "    def create(cls, name: str) -> 'Service': ...\n"
    )
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert "sym:src/x.py::Service.create(name: str) -> 'Service'" in keys


def test_python_symbols_complex_generic_params():
    """Parâmetros complexos com genéricos são preservados na assinatura."""
    source = (
        "def process(items: list[dict[str, Any]], *, callback: Callable[[str], None] = None) -> bool:\n"
        "    pass\n"
    )
    keys = [item.key for item in resume.python_symbols("src/x.py", source)]
    assert any(
        "process(items: list[dict[str, Any]], *, callback: Callable[[str], None]=None) -> bool" in k
        for k in keys
    )


def test_missing_items_symbol_in_wrong_file_section():
    """Símbolo descrito na seção de outro arquivo não conta para o seu próprio arquivo."""
    items = [
        resume.Item("sym", "src/a.py", "save", "()"),
        resume.Item("sym", "src/b.py", "save", "()"),
    ]
    text = (
        "### `src/a.py`\n\n- `save()` — salva no arquivo a.\n\n"
        "### `src/b.py`\n\n- `outro()` — outra função.\n"
    )
    missing = [item.key for item in resume.missing_items(items, text)]
    assert "sym:src/b.py::save()" in missing


def test_missing_items_symbol_outside_section():
    """Símbolo mencionado fora de qualquer seção de arquivo não conta."""
    items = [resume.Item("sym", "src/a.py", "run", "()")]
    text = "Algum texto que menciona `run()` mas não está em uma seção.\n"
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == ["sym:src/a.py::run()"]

def test_file_sections_duplicate_sections_accumulate_all():
    """Quando o mesmo arquivo aparece em múltiplas seções, todo o conteúdo é acumulado."""
    text = (
        "### `src/a.py`\n\n- `run()` — primeira seção.\n\n"
        "### `src/b.py`\n\n- `outro()`\n\n"
        "### `src/a.py`\n\n- `save()` — segunda seção.\n"
    )
    sections = resume.file_sections(text)
    # Agora o conteúdo de todas as seções com o mesmo caminho é acumulado
    assert sections["src/a.py"].count("run()") == 1
    assert sections["src/a.py"].count("save()") == 1  # segunda seção também é incluída

def test_missing_items_duplicate_section_symbol_found():
    """Símbolo descrito em qualquer seção duplicada do mesmo arquivo é encontrado."""
    items = [resume.Item("sym", "src/a.py", "save", "()")]
    text = (
        "### `src/a.py`\n\n- `run()` — primeira seção.\n\n"
        "### `src/b.py`\n\n- `outro()`\n\n"
        "### `src/a.py`\n\n- `save()` — segunda seção.\n"
    )
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == []



def test_missing_items_incidental_mention_in_description():
    """Menção incidental de um símbolo em uma descrição não conta como documentação."""
    items = [resume.Item("sym", "src/a.py", "helper", "()")]
    text = (
        "### `src/a.py`\n\n"
        "- `run()` — executa o fluxo principal, que chama helper() internamente.\n"
    )
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == ["sym:src/a.py::helper()"]

def test_missing_items_symbol_in_code_block():
    """Símbolo dentro de um bloco de código não conta como documentação."""
    items = [resume.Item("sym", "src/a.py", "process", "()")]
    text = (
        "### `src/a.py`\n\n"
        "- `run()` — exemplo:\n"
        "```python\n"
        "process()\n"
        "```\n"
    )
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == ["sym:src/a.py::process()"]

def test_file_sections_no_section_for_file():
    """Arquivo sem seção documental no resume.md."""
    items = [resume.Item("file", "src/novo.py")]
    text = "## `outra/`\n\n- algo\n"
    missing = [item.key for item in resume.missing_items(items, text)]
    assert missing == ["file:src/novo.py"]

def test_inventory_detects_new_items():
    """Inventário novo: item que existe no código mas não no carimbo."""
    current = {"sym:src/a.py::run()", "file:src/b.py"}
    stored = {"sym:src/a.py::run()"}
    added = sorted(current - stored)
    assert "file:src/b.py" in added

def test_inventory_detects_removed_items():
    """Inventário removido: item que estava no carimbo mas não existe mais."""
    current = {"sym:src/a.py::run()"}
    stored = {"sym:src/a.py::run()", "file:src/antigo.py"}
    removed = sorted(stored - current)
    assert "file:src/antigo.py" in removed

def test_inventory_detects_signature_change():
    """Assinatura alterada: mesma chave com assinatura diferente conta como removido/adicionado."""
    current = {"sym:src/a.py::run(x: int)"}
    stored = {"sym:src/a.py::run()"}
    added = sorted(current - stored)
    removed = sorted(stored - current)
    assert "sym:src/a.py::run(x: int)" in added
    assert "sym:src/a.py::run()" in removed


