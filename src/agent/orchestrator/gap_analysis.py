"""
Arquivo: src/agent/orchestrator/gap_analysis.py
Nome: gap_analysis.py
Propósito: transformar um pedido vago de conclusão ("termine", "finalize", "melhore") sobre um projeto existente em requisitos concretos e verificáveis, antes do plano.
Responsabilidade: camada de aplicação — detecção da intenção, leitura curta do projeto, uma chamada ao modelo e normalização das lacunas em requisitos.
Componentes: wants_completion, project_snapshot, analyze_gaps, gap_requirements, environment_note.
Dependências: agent.providers (contrato do modelo), agent.providers.observed, agent.util.json_parse, agent.tools.app_runner.
Observações: roda uma vez, no plano da raiz; sem lacuna útil, nada muda (o pedido segue como estava).

Por que existe
--------------
Visto com o `qwen3-vl:8b` em "sua missão é terminar essa calculadora e abrir ela para mim ver": o
único requisito era a frase inteira, e o modelo pequeno decidiu sozinho, no escuro, que "terminar"
era conferir arquivos — o run concluiu sem melhorar nada e afirmou que "todas as funcionalidades
foram corrigidas". Com as lacunas escritas como requisitos, a maquinaria que já existe (cobertura
do plano, evidência por requisito, aceite global) passa a cobrar cada uma.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    LLMProvider,
    ModelProfile,
)
from agent.tools.app_runner import interpreter_for, is_gui_script
from agent.util.json_parse import parse_json_object

_COMPLETION = re.compile(
    r"\b(termin\w*|finaliz\w*|conclu[ai]\w*|complet\w*|melhor[ae]\w*|aprimor\w*|poli[rd]\w*|deix\w* pront\w*|acab\w*)\b",
    re.IGNORECASE,
)
_SOURCE = {".py", ".js", ".ts", ".html", ".css", ".jsx", ".tsx", ".vue"}
_SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", "dist", "build"}
MAX_GAPS = 6
_SNIPPET = 3500
# Nota de ambiente por raiz de projeto: a sondagem custa processos e não muda na sessão.
_ENV_NOTES: dict[str, str] = {}


def wants_completion(objective: str) -> bool:
    """Diz se o pedido é de conclusão/melhoria de algo que já existe, sem itens enumerados."""
    text = objective or ""
    if re.search(r"^\s*(?:[-*•]|\d+[.)])\s+", text, re.MULTILINE):
        return False
    return bool(_COMPLETION.search(text))


def _sources(root: Path) -> list[Path]:
    """Arquivos de código do projeto, os de teste por último."""
    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in _SOURCE and not any(part in _SKIP for part in p.relative_to(root).parts)
    ]
    return sorted(files, key=lambda p: ("test" in p.name.lower(), len(p.relative_to(root).parts), p.name))


def project_snapshot(project_root: str, *, max_files: int = 4) -> str:
    """Lista de arquivos e o começo dos principais, para o modelo julgar o que falta.

    Args:
        project_root: raiz do projeto.
        max_files: quantos arquivos mostrar por inteiro (até `_SNIPPET` caracteres cada).

    Returns:
        Texto com a árvore curta e os trechos; vazio quando o projeto não tem código.
    """
    root = Path(project_root)
    if not root.is_dir():
        return ""
    files = _sources(root)
    if not files:
        return ""
    lines = ["Arquivos:"] + [f"- {p.relative_to(root)}" for p in files[:30]]
    for path in files[:max_files]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cut = text[:_SNIPPET] + ("\n…(cortado)" if len(text) > _SNIPPET else "")
        lines += ["", f"### {path.relative_to(root)}", cut]
    return "\n".join(lines)


def environment_note(project_root: str) -> str:
    """Fato do ambiente que muda como a interface deve ser escrita (o modelo não tem como saber).

    Hoje cobre o Tkinter: no macOS, quando a janela só abre com o Tk 8.5 do sistema, botões nativos
    ignoram cor de fundo e campos sem cor explícita somem no modo escuro.

    Returns:
        A observação em uma frase, ou vazio.
    """
    if project_root in _ENV_NOTES:
        return _ENV_NOTES[project_root]
    note = _environment_note(project_root)
    _ENV_NOTES[project_root] = note
    return note


def _environment_note(project_root: str) -> str:
    """Sondagem de `environment_note`, sem a memória."""
    root = Path(project_root)
    if not root.is_dir():
        return ""
    gui = next((p for p in _sources(root) if p.suffix == ".py" and is_gui_script(p)), None)
    if gui is None:
        return ""
    import sys

    python, missing = interpreter_for(gui, sys.executable)
    if python is None:
        return f"Ambiente: nenhum Python desta máquina abre janelas {missing}."
    try:
        out = subprocess.run([python, "-c", "import tkinter; print(tkinter.TkVersion)"], capture_output=True, text=True, timeout=15, check=False)
        version = float((out.stdout or "0").strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    if 0 < version < 8.6:
        return (
            f"Ambiente: a janela roda com Tk {version} ({python}). Nessa versão, defina cores explícitas "
            "(bg, fg, insertbackground) em todos os widgets e use tk.Label clicável (bind <Button-1>) "
            "no lugar de tk.Button para botões coloridos; sem isso campos e textos somem no modo escuro."
        )
    return ""


def _prompt(objective: str, snapshot: str, environment: str) -> str:
    """Pedido de lacunas ao modelo."""
    env = f"\n{environment}\n" if environment else "\n"
    return (
        "Você é revisor de produto. O usuário pediu:\n"
        f"«{objective}»\n\n"
        "Este é o projeto atual:\n"
        f"{snapshot}\n{env}\n"
        f"Liste de 3 a {MAX_GAPS} lacunas concretas que impedem este projeto de ser um produto pronto e "
        "bem feito para esse pedido (funcionalidade que falta, defeito, interface pobre, erro não tratado). "
        "Cada item é uma frase imperativa curta que começa citando o arquivo a mudar, por exemplo "
        "'em main.py, ...'. Nada de tarefas de conferir ou revisar: só o que precisa mudar. "
        "Não inclua mudanças em arquivos de teste (eles são a régua e ficam protegidos) nem remoção de "
        "código que outro arquivo usa. "
        'Responda SOMENTE JSON: {"lacunas": ["...", "..."]}'
    )


# Lacuna que mexe em teste é impossível com a régua protegida: o requisito ficaria sem prova para sempre.
_TEST_FILE = re.compile(r"(?:^|[\s/])(?:tests?/|test_\w+\.py|\w+_test\.py)", re.IGNORECASE)


def _clean(items: Any) -> list[str]:
    """Lacunas válidas: 12 a 240 caracteres, sem repetição, sem arquivo de teste, no máximo `MAX_GAPS`."""
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        text = " ".join(str(item or "").split())
        if not 12 <= len(text) <= 240 or _TEST_FILE.search(text):
            continue
        if text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:MAX_GAPS]


async def analyze_gaps(
    provider: LLMProvider, profile: ModelProfile, objective: str, project_root: str
) -> list[str]:
    """Pede ao modelo as lacunas que separam o projeto do pedido.

    Args:
        provider: modelo do run.
        profile: perfil do modelo.
        objective: pedido do usuário.
        project_root: raiz do projeto.

    Returns:
        As lacunas (frases imperativas), ou lista vazia quando o projeto não tem código, o modelo
        falha ou a resposta não serve — o pedido então segue sem elas.
    """
    snapshot = project_snapshot(project_root)
    if not snapshot:
        return []
    from agent.providers.observed import observed_chat

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=_prompt(objective, snapshot, environment_note(project_root)))],
        profile=profile,
    )
    try:
        resp = await observed_chat(provider, request, purpose="plan")
    except Exception:  # noqa: BLE001 — falha do modelo aqui não pode impedir o plano
        return []
    data, _err = parse_json_object(resp.content or "")
    if not isinstance(data, dict):
        return []
    return _clean(data.get("lacunas") or data.get("gaps") or data.get("itens"))


def gap_requirements(gaps: list[str], start: int) -> list[dict[str, Any]]:
    """Lacunas no formato de requisito do contrato, numeradas a partir de `start`.

    Args:
        gaps: lacunas devolvidas por `analyze_gaps`.
        start: número do primeiro requisito novo (os existentes mantêm seus ids).

    Returns:
        Requisitos obrigatórios, de evidência `change`, com origem "lacuna do pedido".
    """
    return [
        {
            "id": f"R{start + index}",
            "description": text,
            "origin": "lacuna do pedido",
            "criterion": f"Atendido com evidência: {text}",
            "applicability": "obrigatório",
            "evidence": "change",
            "refs": [],
        }
        for index, text in enumerate(gaps)
    ]
