"""
Arquivo: tests/test_app_runner.py
Nome: test_app_runner.py
Propósito: verificar como o Callidus roda programas de janela do projeto: prova curta que não trava, abertura que deixa o programa aberto e sinônimos de `path`.
Responsabilidade: camada de testes — is_gui_script, smoke_run, launch_detached, run_app/open_path/launch_app com .py e normalize_arguments.
Componentes: programa que fica vivo, programa que cai com erro, abertura em segundo plano, roteamento de .py para run_app, sinônimos de path.
Dependências: agent.tools.app_runner, agent.tools.arguments, agent.tools.registry, pytest.
Observações: os "programas de janela" são scripts que dormem (sem abrir janela de verdade), para rodar em qualquer máquina sem tela.
"""

import os
import signal
import sys

import pytest

from agent.tools.app_runner import is_gui_script, launch_detached, smoke_run
from agent.tools.arguments import normalize_arguments
from agent.tools.registry import ToolContext, build_default_registry


def test_is_gui_script_reads_toolkit_imports(tmp_path):
    """Importar um toolkit gráfico marca o script como programa de janela; citar em comentário, não."""
    gui = tmp_path / "main.py"
    gui.write_text("import tkinter as tk\nroot = tk.Tk()\nroot.mainloop()\n", encoding="utf-8")
    plain = tmp_path / "calc.py"
    plain.write_text("# usa tkinter depois\ndef add(a, b):\n    return a + b\n", encoding="utf-8")
    assert is_gui_script(gui) is True
    assert is_gui_script(plain) is False


@pytest.mark.asyncio
async def test_smoke_run_passes_when_the_program_stays_open():
    """Regressão: rodar uma janela esperando o fim travava até o tempo esgotar; agora "ficou aberta" passa."""
    out = await smoke_run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=".", env=None, seconds=1.0)
    assert out["success"] is True and out["gui"]["still_running"] is True


@pytest.mark.asyncio
async def test_smoke_run_fails_with_the_error_when_the_program_crashes():
    """Programa que cai ao abrir reprova com a saída de erro, para a etapa reagir à causa."""
    out = await smoke_run([sys.executable, "-c", "raise SystemExit('janela quebrou')"], cwd=".", env=None, seconds=3.0)
    assert out["success"] is False and "janela quebrou" in out["stderr"]


@pytest.mark.asyncio
async def test_launch_detached_leaves_the_program_running(tmp_path):
    """"Abrir para o usuário ver": o programa continua aberto depois que a ferramenta devolve."""
    out = await launch_detached([sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(tmp_path), env=None, settle=0.5)
    try:
        assert out["success"] is True and out["running"] is True
    finally:
        os.kill(out["pid"], signal.SIGTERM)

    caiu = await launch_detached([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=str(tmp_path), env=None, settle=1.0)
    assert caiu["success"] is False and "3" in caiu["error"]


@pytest.mark.asyncio
async def test_run_app_and_open_path_run_the_project_script(tmp_path):
    """run_app (e open_path/launch_app com um .py do projeto) roda o programa, não abre o código no editor."""
    (tmp_path / "main.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))
    pids = []
    try:
        for tool, args in (("run_app", {"path": "main.py"}), ("open_app", {"script_path": "main.py"}), ("open_path", {"path": "main.py"})):
            out = await reg.execute(tool, ctx, args, approved=True)
            assert out["success"] is True and out["running"] is True, (tool, out)
            pids.append(out["pid"])
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # reabrir o mesmo programa já fechou a janela anterior


def test_normalize_arguments_fills_path_from_synonyms():
    """Regressão (qwen3-vl:8b): run_script com `script_path` falhava duas vezes por falta de `path`."""
    schema = {"path": "str"}
    assert normalize_arguments(schema, {"script_path": "main.py"})["path"] == "main.py"
    assert normalize_arguments(schema, {"command": "python3 main.py"})["path"] == "main.py"
    assert normalize_arguments(schema, {"path": "a.py", "file": "b.py"})["path"] == "a.py"
    assert "path" not in normalize_arguments({"path": "str?"}, {"file": "b.py"})
    assert "path" not in normalize_arguments(schema, {"command": "python a.py b.py"})


@pytest.mark.asyncio
async def test_smoke_run_events_follow_the_contract_inside_a_run(tmp_path):
    """Regressão: dentro de um run, o evento da prova de janela saía sem `call_id`/`error` e o passo caía."""
    from agent.observability.contracts import validate_payload

    captured = []
    import agent.tools.app_runner as runner_module

    original = runner_module.emit
    runner_module.emit = lambda kind, data=None, **kw: captured.append((kind, validate_payload(kind, data)))
    try:
        await smoke_run([sys.executable, "-c", "raise SystemExit(2)"], cwd=".", env=None, seconds=2.0)
        await smoke_run([sys.executable, "-c", "import time; time.sleep(5)"], cwd=".", env=None, seconds=0.5)
        out = await launch_detached([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), env=None, settle=0.3)
        os.kill(out["pid"], signal.SIGTERM)
    finally:
        runner_module.emit = original
    assert [kind for kind, _ in captured] == ["command.failed", "command.completed", "app.launched"]


def test_interpreter_for_picks_a_python_that_has_the_toolkit(tmp_path, monkeypatch):
    """Regressão (Mac do dono): o Python do projeto não tinha `_tkinter`; o /usr/bin/python3 tinha.
    A janela deve abrir com o capaz; sem nenhum capaz, a falha é de configuração com a instrução."""
    import agent.tools.app_runner as runner_module
    from agent.tools.app_runner import interpreter_for, missing_toolkit_result

    script = tmp_path / "main.py"
    script.write_text("import tkinter as tk\ntk.Tk().mainloop()\n", encoding="utf-8")
    sem_tk, com_tk = str(tmp_path / "sem_tk"), str(tmp_path / "com_tk")
    for fake in (sem_tk, com_tk):
        open(fake, "w").close()
    monkeypatch.setattr(runner_module, "_CANDIDATES", (com_tk,))
    monkeypatch.setattr(runner_module, "_imports_ok", lambda python, module: python == com_tk and module == "tkinter")

    assert interpreter_for(script, sem_tk) == (com_tk, None)
    monkeypatch.setattr(runner_module, "_imports_ok", lambda python, module: False)
    assert interpreter_for(script, sem_tk) == (None, "tkinter")
    falha = missing_toolkit_result("tkinter", [sem_tk, str(script)])
    assert falha["category"] == "configuration" and "python-tk" in falha["error"]

    plain = tmp_path / "calc.py"
    plain.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert interpreter_for(plain, sem_tk) == (sem_tk, None)


@pytest.mark.asyncio
async def test_reopening_the_same_program_closes_the_previous_window(tmp_path):
    """Regressão: cada volta do run chamava run_app e empilhava janelas da calculadora."""
    script = tmp_path / "main.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    first = await launch_detached([sys.executable, str(script)], cwd=str(tmp_path), env=None, settle=0.3)
    second = await launch_detached([sys.executable, str(script)], cwd=str(tmp_path), env=None, settle=0.3)
    try:
        import time as _time

        _time.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.kill(first["pid"], 0)  # a primeira janela foi fechada
        os.kill(second["pid"], 0)  # a nova continua aberta
    finally:
        os.kill(second["pid"], signal.SIGTERM)


def _tk_python():
    """Um Python com Tk e tela disponível, ou `None` (a prova de botões precisa abrir janela)."""
    import shutil
    import subprocess
    from pathlib import Path

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return None
    for python in (sys.executable, "/usr/bin/python3", shutil.which("python3") or ""):
        if python and Path(python).exists():
            done = subprocess.run([python, "-c", "import tkinter; tkinter.Tk().destroy()"], capture_output=True, timeout=20, check=False)
            if done.returncode == 0:
                return python
    return None


@pytest.mark.asyncio
async def test_tk_probe_clicks_every_button_and_reports_a_broken_callback(tmp_path):
    """Regressão (qwen3-vl:8b): `self.entry2.deleteee(...)` passava — a janela abria; só o clique quebrava."""
    from agent.tools.app_runner import tk_probe_command

    python = _tk_python()
    if python is None:
        pytest.skip("sem Tk com tela nesta máquina")
    app = (
        "import tkinter as tk\n"
        "root = tk.Tk()\n"
        "e = tk.Entry(root); e.pack()\n"
        "tk.Button(root, text='Somar', command=lambda: int(e.get()) + 1).pack()\n"
        "tk.Button(root, text='Clear', command=lambda: e.deleteee(0, tk.END)).pack()\n"
        "root.mainloop()\n"
    )
    script = tmp_path / "main.py"
    script.write_text(app, encoding="utf-8")
    broken = await smoke_run(tk_probe_command(python, script), cwd=str(tmp_path), env=None, seconds=20)
    assert broken["success"] is False and "deleteee" in broken["stderr"]

    script.write_text(app.replace("deleteee", "delete"), encoding="utf-8")
    fine = await smoke_run(tk_probe_command(python, script), cwd=str(tmp_path), env=None, seconds=20)
    assert fine["success"] is True and "2 botões" in fine["summary"], fine


@pytest.mark.asyncio
async def test_search_grep_on_a_huge_root_is_bounded_and_does_not_block(tmp_path, monkeypatch):
    """Regressão: com a raiz na pasta pessoal, um search_grep síncrono e sem limite parou o servidor.
    Agora a varredura roda fora do loop, com teto, e avisa que o resultado é parcial."""
    import asyncio

    from agent.tools import builtins

    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("nada aqui\n", encoding="utf-8")
    monkeypatch.setattr(builtins, "SCAN_MAX_FILES", 5)
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    out = await reg.execute("search_grep", ctx, {"pattern": "calculadora"})
    task.cancel()
    assert out["success"] is True and out["count"] == 0
    assert "partial" in out and "path" in out["partial"]
    assert ticks > 0  # o loop continuou atendendo enquanto a busca rodava


@pytest.mark.asyncio
async def test_edit_file_fixes_the_indentation_the_model_dropped(tmp_path):
    """Regressão (qwen3-vl:8b): edit_file sem a indentação do método dava "unexpected indent" duas vezes
    e bloqueava a etapa; agora a troca entra com a indentação do lugar, e só se o arquivo ficar válido."""
    import ast

    src = "class A:\n    def __init__(self):\n        self.x = 1\n        self.y = 2\n"
    (tmp_path / "main.py").write_text(src, encoding="utf-8")
    reg = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))

    out = await reg.execute("edit_file", ctx, {"path": "main.py", "old_string": "self.x = 1", "new_string": "self.x = 1\nself.z = 3"})
    assert out["success"] and out.get("reindented")
    texto = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(texto)
    assert "        self.z = 3" in texto

    out = await reg.execute("edit_file", ctx, {"path": "main.py", "old_string": "self.x = 1\nself.z = 3", "new_string": "self.x = 10\nself.z = 30"})
    assert out["success"] and out.get("reindented")
    assert "        self.z = 30" in (tmp_path / "main.py").read_text(encoding="utf-8")

    (tmp_path / "notas.txt").write_text("a\n  b\n", encoding="utf-8")
    nao = await reg.execute("edit_file", ctx, {"path": "notas.txt", "old_string": "b\nc", "new_string": "x"})
    assert not nao["success"]
