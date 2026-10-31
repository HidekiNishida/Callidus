"""
Arquivo: src/agent/tools/app_runner.py
Nome: app_runner.py
Propósito: rodar programas de janela (Tkinter, PyQt, pygame...) do projeto sem travar o agente: conferir que abrem e deixá-los abertos para o usuário.
Responsabilidade: camada de infraestrutura — detecção de programa de janela, execução de prova por tempo curto e abertura em segundo plano.
Componentes: is_gui_script, gui_module, interpreter_for, tk_probe_command, TK_PROBE, smoke_run, launch_detached, _spawn.
Dependências: asyncio, subprocess, agent.observability, agent.tools.registry.
Observações: um programa de janela não termina sozinho; rodado como script comum ele estourava o tempo e a etapa reprovava sempre.

Por que existe
--------------
Visto com o `qwen3-vl:8b` no pedido "termine a calculadora e abra para eu ver": a verificação rodava
`main.py` (Tkinter) esperando o fim do processo, que só acontece quando alguém fecha a janela. A
prova útil é outra: o programa **abriu e continuou vivo** por alguns segundos sem erro. E "abrir
para o usuário ver" é iniciar o programa em segundo plano e deixá-lo aberto.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from agent.observability import emit
from agent.tools.registry import current_call_id

# Importação de um toolkit de janela no começo de uma linha (não em comentário nem em string).
_GUI_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:tkinter|Tkinter|customtkinter|ttkbootstrap|PyQt5|PyQt6|PySide2|PySide6|pygame|wx|kivy|turtle|flet|pyglet|arcade)\b",
    re.MULTILINE,
)
# Processos abertos para o usuário: a referência evita que o objeto seja coletado e vire zumbi.
_LAUNCHED: dict[int, subprocess.Popen] = {}
# Programa → processo aberto: reabrir o mesmo programa fecha a janela anterior (uma por programa).
_BY_SCRIPT: dict[str, subprocess.Popen] = {}
# Pythons conhecidos da máquina, testados depois do interpretador do projeto.
_CANDIDATES = (
    "/usr/bin/python3",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
)
# (interpretador, módulo) → importou? A sondagem custa um processo; a resposta não muda na sessão.
_PROBED: dict[tuple[str, str], bool] = {}
# Módulo que precisa importar para o toolkit funcionar (o Tkinter depende de `_tkinter`, que o
# Python do Homebrew não traz sem o pacote python-tk).
_PROBE_MODULE = {"tkinter": "tkinter", "Tkinter": "tkinter", "customtkinter": "tkinter", "ttkbootstrap": "tkinter", "turtle": "tkinter"}


def is_gui_script(path: Path) -> bool:
    """Diz se o script abre uma janela (importa um toolkit gráfico).

    Args:
        path: arquivo Python do projeto.

    Returns:
        Verdadeiro quando o arquivo importa Tkinter, PyQt, PySide, pygame, wx, kivy, turtle e afins.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_GUI_IMPORT.search(text))


def gui_module(path: Path) -> str | None:
    """Toolkit de janela que o script importa (`tkinter`, `PyQt6`...), ou `None`."""
    try:
        match = _GUI_IMPORT.search(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not match:
        return None
    return match.group(0).split()[1].split(".")[0]


def _imports_ok(python: str, module: str) -> bool:
    """Diz se `python` consegue importar `module` (resposta guardada)."""
    key = (python, module)
    if key not in _PROBED:
        try:
            done = subprocess.run([python, "-c", f"import {module}"], capture_output=True, timeout=15, check=False)
            _PROBED[key] = done.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _PROBED[key] = False
    return _PROBED[key]


def interpreter_for(script: Path, preferred: str) -> tuple[str | None, str | None]:
    """Escolhe um Python capaz de abrir o programa de janela.

    Visto no Mac do dono: o Python do Homebrew (o do ambiente do Callidus) não tem `_tkinter`; a
    janela caía com `ModuleNotFoundError` e o run replanejava sem fim, porque nenhuma mudança no
    código resolve falta de módulo no interpretador. O `/usr/bin/python3` do macOS tem Tk.

    Args:
        script: programa de janela do projeto.
        preferred: interpretador do projeto (o `.venv` dele ou o do agente), testado primeiro.

    Returns:
        `(interpretador, None)` com o primeiro que importa o toolkit; `(None, toolkit)` quando nenhum
        importa; `(preferred, None)` quando o script não é de janela.
    """
    toolkit = gui_module(script)
    if toolkit is None:
        return preferred, None
    module = _PROBE_MODULE.get(toolkit, toolkit)
    seen: list[str] = []
    for python in (preferred, *_CANDIDATES):
        if python in seen or not Path(python).exists():
            continue
        seen.append(python)
        if _imports_ok(python, module):
            return python, None
    return None, toolkit


def missing_toolkit_result(toolkit: str, command: list[str]) -> dict[str, Any]:
    """Falha de **configuração** quando nenhum Python da máquina tem o toolkit de janela.

    A categoria `configuration` faz o orquestrador parar com a ação a tomar, em vez de repetir.
    """
    hint = "brew install python-tk" if toolkit in _PROBE_MODULE else f"pip install {toolkit}"
    return {
        "success": False,
        "error": f"nenhum Python desta máquina tem o módulo {toolkit} para abrir a janela; instale com: {hint}",
        "category": "configuration",
        "command": command,
    }


# Prova de Tkinter: roda o programa com os diálogos neutralizados, preenche os campos vazios,
# aciona cada botão (e cada widget com clique ligado por `bind`) e registra o erro de qualquer
# callback. Visto com o `qwen3-vl:8b`: `self.entry2.deleteee(...)` passava (sintaxe ok, a janela
# abria) e só quebrava quando alguém clicava em "Clear". Compatível com o Python 3.9 do macOS.
TK_PROBE = r"""
import runpy, sys, traceback
script = sys.argv[1]
sys.argv = [script]
errors, clicked = [], []
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
except Exception:
    runpy.run_path(script, run_name="__main__")
    sys.exit(0)
for mod, names in ((messagebox, ("showinfo", "showwarning", "showerror", "askquestion", "askokcancel", "askyesno", "askyesnocancel", "askretrycancel")),
                   (simpledialog, ("askstring", "askinteger", "askfloat")),
                   (filedialog, ("askopenfilename", "asksaveasfilename", "askdirectory", "askopenfilenames"))):
    for name in names:
        if hasattr(mod, name):
            setattr(mod, name, lambda *a, **k: None)
def _report(self, exc, val, tb):
    errors.append("".join(traceback.format_exception(exc, val, tb)).strip())
tk.Tk.report_callback_exception = _report
SKIP = {"quit", "sair", "exit", "fechar", "close"}
def _walk(widget):
    for child in widget.winfo_children():
        yield child
        for sub in _walk(child):
            yield sub
_mainloop = tk.Misc.mainloop
def _probe(self, n=0):
    root = self._root()
    def run():
        widgets = list(_walk(root))
        for w in widgets:
            try:
                if w.winfo_class() in ("Entry", "TEntry") and not w.get() and str(w.cget("state")) == "normal":
                    w.insert(0, "3")
            except Exception:
                pass
        for w in widgets:
            try:
                cls = w.winfo_class()
                text = str(w.cget("text")) if "text" in w.keys() else cls
                bound = w.bind()
            except tk.TclError:
                continue
            if text.strip().lower() in SKIP:
                continue
            try:
                if cls in ("Button", "TButton"):
                    w.invoke()
                    clicked.append(text)
                elif "<Button-1>" in bound or "<ButtonPress-1>" in bound or "<ButtonRelease-1>" in bound:
                    w.event_generate("<Button-1>")
                    w.event_generate("<ButtonRelease-1>")
                    clicked.append(text)
            except tk.TclError as exc:
                if "destroyed" in str(exc):
                    break
                errors.append("botão %r: %s" % (text, exc))
            except Exception:
                errors.append("botão %r: %s" % (text, traceback.format_exc().strip()))
        root.after(150, root.destroy)
    root.after(600, run)
    _mainloop(root)
tk.Misc.mainloop = _probe
tk.mainloop = lambda n=0: _probe(tk._default_root) if tk._default_root else None
runpy.run_path(script, run_name="__main__")
if errors:
    sys.stderr.write("\n".join(errors) + "\n")
    sys.exit(1)
print("PROVA_OK %d botões: %s" % (len(clicked), ", ".join(clicked)[:400]))
"""
_TK_TOOLKITS = {"tkinter", "Tkinter", "customtkinter", "ttkbootstrap"}


def tk_probe_command(python: str, script: Path) -> list[str] | None:
    """Comando da prova dos botões quando o script usa Tkinter; `None` para outros toolkits.

    Args:
        python: interpretador que tem o Tk.
        script: programa de janela do projeto.

    Returns:
        `[python, "-c", TK_PROBE, script]`, ou `None` quando o toolkit não é Tkinter (vale a prova
        de abrir e ficar aberto).
    """
    if gui_module(script) not in _TK_TOOLKITS:
        return None
    return [python, "-c", TK_PROBE, str(script)]


async def smoke_run(command: list[str], *, cwd: str, env: dict[str, str] | None, seconds: float = 5.0) -> dict[str, Any]:
    """Roda um programa de janela por alguns segundos para provar que ele abre sem erro.

    Args:
        command: comando (interpretador + script).
        cwd: diretório de trabalho.
        env: ambiente do processo.
        seconds: por quanto tempo o programa precisa continuar vivo.

    Returns:
        O mesmo formato do `run_command` (`success`, `exit_code`, `stdout`, `stderr`, `command`) e
        `gui`: `still_running` verdadeiro quando o programa ficou aberto e foi encerrado pela prova.
        Saiu antes com erro → `success` falso e a saída de erro; saiu com 0 → sucesso normal.
    """
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *command, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    still_running = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=seconds)
    except TimeoutError:
        still_running = True
        proc.terminate()
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=3)
        except TimeoutError:
            proc.kill()
            out, err = await proc.communicate()
    stdout = (out or b"").decode("utf-8", errors="replace")
    stderr = (err or b"").decode("utf-8", errors="replace")
    ok = still_running or proc.returncode == 0
    finished = {
        "call_id": current_call_id() or uuid.uuid4().hex[:12],
        "command": " ".join(command),
        "exit_code": 0 if still_running else proc.returncode,
        "gui_smoke": True,
        "still_running": still_running,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stderr_tail": stderr[-2000:],
    }
    if ok:
        emit("command.completed", finished)
    else:
        emit("command.failed", {**finished, "error": f"o programa fechou com erro (código {proc.returncode})"})
    return {
        "success": ok,
        "exit_code": 0 if still_running else proc.returncode,
        "stdout": stdout[-8000:],
        "stderr": stderr[-8000:],
        "command": command,
        "gui": {"still_running": still_running, "seconds": seconds},
        "summary": (
            f"a janela abriu e ficou aberta {seconds:.0f} s sem erro (encerrada pela verificação)"
            if still_running
            else (
                stdout.strip().splitlines()[-1].replace("PROVA_OK", "a janela abriu e acionei", 1)
                if ok and "PROVA_OK" in stdout
                else ("o programa terminou sem erro" if ok else "o programa fechou com erro")
            )
        ),
    }


def _spawn(command: list[str], *, cwd: str, env: dict[str, str] | None, log_path: Path) -> subprocess.Popen:
    """Inicia o processo numa sessão própria (sobrevive ao agente), com a saída num arquivo de log."""
    with open(log_path, "wb") as log:
        return subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


async def launch_detached(command: list[str], *, cwd: str, env: dict[str, str] | None, settle: float = 3.0) -> dict[str, Any]:
    """Abre o programa em segundo plano e o deixa aberto para o usuário.

    Args:
        command: comando (interpretador + script).
        cwd: diretório de trabalho.
        env: ambiente do processo.
        settle: quanto esperar para conferir que ele não caiu logo ao abrir.

    Returns:
        `success`, `pid`, `running` e o arquivo de log; se o programa caiu ao abrir, `success` falso
        com o fim do log (o erro), para a etapa reagir à causa.
    """
    log_path = Path(tempfile.gettempdir()) / f"callidus-app-{int(time.time())}-{os.getpid()}.log"
    previous = _BY_SCRIPT.get(command[-1])
    if previous is not None and previous.poll() is None:
        # O usuário vê a versão nova, não uma pilha de janelas antigas.
        previous.terminate()
        try:
            previous.wait(timeout=3)
        except subprocess.TimeoutExpired:
            previous.kill()
    proc = _spawn(command, cwd=cwd, env=env, log_path=log_path)
    waited = 0.0
    while waited < settle and proc.poll() is None:
        await asyncio.sleep(0.25)
        waited += 0.25
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:] if log_path.exists() else ""
    if proc.poll() is not None and proc.returncode != 0:
        emit(
            "command.failed",
            {
                "call_id": current_call_id() or uuid.uuid4().hex[:12],
                "command": " ".join(command),
                "exit_code": proc.returncode,
                "error": f"o programa fechou ao abrir (código {proc.returncode})",
                "log_tail": tail,
            },
        )
        return {"success": False, "error": f"o programa fechou ao abrir (código {proc.returncode})", "log": tail, "command": command}
    running = proc.poll() is None
    if running:
        _LAUNCHED[proc.pid] = proc
        _BY_SCRIPT[command[-1]] = proc
    emit("app.launched", {"app": Path(command[-1]).name, "command": " ".join(command), "pid": proc.pid, "running": running})
    return {
        "success": True,
        "pid": proc.pid,
        "running": running,
        "log_path": str(log_path),
        "command": command,
        "summary": "o programa está aberto" if running else "o programa rodou e terminou sem erro",
    }
