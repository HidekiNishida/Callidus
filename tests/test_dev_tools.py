"""
Arquivo: tests/test_dev_tools.py
Nome: test_dev_tools.py
Propósito: Verificar as ferramentas de desenvolvimento e o verificador de scripts.
Responsabilidade: camada de testes — listagem, glob, edição, leitura por janela, remoção aprovada, busca, shell, pytest sem testes e verificação por script.
Componentes: conjunto de ferramentas do registro, alias, aprovação exigida na remoção, grep sem venv, execução de comando, interpretador do venv e verificação por script.
Dependências: agent.tools.registry, agent.tools.builtins e agent.verification.runner.
Observações: filesystem temporário em tmp_path; o shell executa apenas comandos locais de teste.
"""

import sys

import pytest

from agent.tools.builtins import python_for
from agent.tools.registry import ToolContext, build_default_registry
from agent.verification.runner import run_verification


@pytest.fixture
def ctx(tmp_path):
    """Contexto de ferramenta sobre um projeto temporário com um pacote e um arquivo de notas."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("alfa\nbeta\n", encoding="utf-8")
    return ToolContext(project_root=str(tmp_path))


@pytest.mark.asyncio
async def test_list_glob_edit_and_aliases(ctx, tmp_path):
    """Listar, globar, editar, ler em janela e criar pasta funcionam, e remover sem aprovação é recusado."""
    reg = build_default_registry()
    listed = await reg.execute("ls", ctx, {"path": "."})
    assert listed["success"]
    assert any(item["path"] == "pkg" for item in listed["entries"])

    found = await reg.execute("glob", ctx, {"pattern": "**/*.py"})
    assert found["success"]
    assert "pkg/app.py" in found["matches"]

    edited = await reg.execute(
        "str_replace",
        ctx,
        {"path": "pkg/app.py", "old_string": "a - b", "new_string": "a + b"},
    )
    assert edited["success"]
    assert "a + b" in (tmp_path / "pkg" / "app.py").read_text(encoding="utf-8")

    window = await reg.execute("read_file", ctx, {"path": "notes.md", "offset": 2, "limit": 1})
    assert window["content"] == "beta"
    assert window["total_lines"] == 2

    made = await reg.execute("mkdir", ctx, {"path": "out"})
    assert made["success"] and (tmp_path / "out").is_dir()

    denied = await reg.execute("delete", ctx, {"path": "notes.md"})
    assert denied["error"] == "approval_required"
    removed = await reg.execute("rm", ctx, {"path": "notes.md"}, approved=True)
    assert removed["success"]
    assert not (tmp_path / "notes.md").exists()


@pytest.mark.asyncio
async def test_grep_skips_venv_and_command_string(ctx, tmp_path):
    """A busca ignora a pasta de dependências e o comando de shell devolve a saída esperada."""
    vendor = tmp_path / ".venv" / "lib"
    vendor.mkdir(parents=True)
    (vendor / "hidden.py").write_text("def secret():\n    pass\n", encoding="utf-8")
    reg = build_default_registry()
    hits = await reg.execute("grep", ctx, {"pattern": "def ", "path": "."})
    assert hits["success"]
    assert all(".venv" not in item["path"] for item in hits["matches"])
    assert any(item["path"] == "pkg/app.py" for item in hits["matches"])

    ran = await reg.execute("shell", ctx, {"command": "python -c 'print(7)'"}, approved=True)
    assert ran["success"]
    assert "7" in ran["stdout"]


@pytest.mark.asyncio
async def test_pytest_without_tests_accepts_html_delivery(tmp_path):
    """Uma entrega em HTML sem testes é aceita pela verificação em pytest."""
    (tmp_path / "index.html").write_text("<h1>Vendas</h1>\n", encoding="utf-8")
    result = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "pytest", "path": "."},
        approved=True,
    )
    assert result.passed is True
    assert "não há testes" in result.summary


@pytest.mark.asyncio
async def test_missing_executable_is_a_configuration_error(ctx):
    """Executável inexistente é classificado como erro de configuração, não de execução."""
    reg = build_default_registry()
    out = await reg.execute("shell", ctx, {"command": ["no-such-binary-xyz", "-v"]}, approved=True)
    assert out["success"] is False
    assert out["category"] == "configuration"
    assert "no-such-binary-xyz" in out["error"]


def test_python_prefers_project_venv(tmp_path):
    """O interpretador escolhido é o do venv do projeto quando ele existe."""
    assert python_for(str(tmp_path)) == sys.executable
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    assert python_for(str(tmp_path)) == str(venv_python)


@pytest.mark.asyncio
async def test_script_verification(tmp_path):
    """A verificação por script roda o script e reporta aprovação."""
    script = tmp_path / "check.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    result = await run_verification(
        project_root=str(tmp_path),
        spec={"type": "script", "path": "check.py"},
        approved=True,
    )
    assert result.passed is True
