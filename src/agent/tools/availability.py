"""
Arquivo: src/agent/tools/availability.py
Nome: availability.py
Propósito: verificar se os pré-requisitos de uma ferramenta existem no ambiente atual.
Responsabilidade: camada de infraestrutura — sondagem de binários, módulos, sistema e ambiente.
Componentes: Requirement, Availability, check_requirement, check_requirements, check_tool.
Dependências: shutil, importlib.util, platform.
Observações: a verificação é barata e sem rede; nunca executa a ferramenta para descobrir se ela existe.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any

from agent.tools.contracts import ToolRisk  # noqa: F401  (mantém o contrato visível no módulo)

#: Sufixos aceitos no requisito `os:`.
_OS_NAMES = {"darwin": "macos", "windows": "windows", "linux": "linux"}


@dataclass(frozen=True)
class Requirement:
    """Um pré-requisito verificável de uma ferramenta.

    Formatos aceitos na forma `tipo:valor`:

    - `binary:npm` — o executável está no `PATH`;
    - `module:playwright` — o pacote Python pode ser importado;
    - `os:macos` — o sistema operacional atual é um dos listados;
    - `env:OPENAI_API_KEY` — a variável de ambiente está definida;
    - `path:/caminho` — o caminho existe no disco;
    - `session:gui` — há sessão gráfica ativa.

    Atributos:
        spec: descrição original do requisito.
        kind: tipo do requisito (`binary`, `module`, `os`, `env`, `path`, `session`).
        value: valor verificado.
    """

    spec: str
    kind: str
    value: str

    @classmethod
    def parse(cls, spec: str) -> Requirement:
        """Interpreta a forma textual do requisito.

        Args:
            spec: requisito no formato `tipo:valor`.

        Returns:
            O requisito interpretado; um requisito `binary` é assumido quando não há prefixo.
        """
        raw = str(spec or "").strip()
        if ":" not in raw:
            return cls(raw, "binary", raw)
        kind, _, value = raw.partition(":")
        return cls(raw, kind.strip().lower(), value.strip())


@dataclass
class Availability:
    """Resultado da verificação de pré-requisitos de uma ferramenta.

    Atributos:
        available: quando `True`, todos os requisitos foram atendidos.
        missing: requisitos não atendidos, na forma original.
        hints: instruções de resolução, uma por requisito ausente.
        details: o que foi observado em cada requisito.
    """

    available: bool
    missing: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)


def _current_os() -> str:
    """Nome canônico do sistema operacional atual.

    Returns:
        `macos`, `windows` ou `linux`.
    """
    return _OS_NAMES.get(platform.system().lower(), platform.system().lower())


def _has_gui_session() -> bool:
    """Indica se há sessão gráfica ativa no ambiente atual.

    Returns:
        `True` quando há servidor de display, Wayland ou sessão de janela.
    """
    if platform.system().lower() == "darwin":
        return True
    if platform.system().lower() == "windows":
        return os.environ.get("SESSIONNAME", "") not in {"", "Services"}
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return True
    return False


def check_requirement(requirement: Requirement) -> tuple[bool, str, str]:
    """Verifica um pré-requisito.

    Args:
        requirement: requisito a verificar.

    Returns:
        Tupla com `atendido`, `observação` e `instrução de resolução` (vazia quando atendido).
    """
    kind = requirement.kind
    value = requirement.value
    if kind == "binary":
        found = shutil.which(value)
        if found:
            return True, found, ""
        return False, "não encontrado no PATH", f"instale o executável '{value}' ou ajuste o PATH"
    if kind == "module":
        try:
            spec = importlib.util.find_spec(value)
        except (ImportError, ValueError):
            spec = None
        if spec is not None:
            return True, value, ""
        return False, "módulo Python ausente", f"instale o pacote Python '{value}' (pip install {value})"
    if kind == "os":
        wanted = {item.strip().lower() for item in value.split(",") if item.strip()}
        current = _current_os()
        if current in wanted or platform.system().lower() in wanted:
            return True, current, ""
        return False, f"sistema atual: {current}", f"a ferramenta exige {', '.join(sorted(wanted))}"
    if kind == "env":
        if os.environ.get(value):
            return True, "definida", ""
        return False, "variável ausente", f"defina a variável de ambiente {value}"
    if kind == "path":
        if os.path.exists(os.path.expanduser(value)):
            return True, value, ""
        return False, "caminho inexistente", f"o caminho {value} não existe neste ambiente"
    if kind == "session":
        wanted = {item.strip().lower() for item in value.split(",") if item.strip()}
        if _has_gui_session():
            return True, "sessão gráfica presente", ""
        if "gui" in wanted:
            return False, "sem sessão gráfica", "a ferramenta exige uma sessão gráfica ativa"
        return True, "sem sessão gráfica", ""
    return True, "requisito desconhecido ignorado", ""


def check_requirements(requirements: list[str]) -> Availability:
    """Verifica uma lista de requisitos.

    Args:
        requirements: requisitos no formato `tipo:valor`.

    Returns:
        O resultado agregado da verificação.
    """
    missing: list[str] = []
    hints: list[str] = []
    details: dict[str, str] = {}
    for raw in requirements or []:
        requirement = Requirement.parse(raw)
        ok, detail, hint = check_requirement(requirement)
        details[raw] = detail
        if not ok:
            missing.append(raw)
            if hint:
                hints.append(hint)
    return Availability(not missing, missing, hints, details)


def check_tool(spec: Any) -> Availability:
    """Verifica os requisitos declarados por uma ferramenta.

    Args:
        spec: `ToolSpec` com os campos `requires` e `platforms`.

    Returns:
        O resultado da verificação; a plataforma só é considerada quando `platforms` é preenchido.
    """
    requirements = list(getattr(spec, "requires", None) or [])
    platforms = [str(item).lower() for item in (getattr(spec, "platforms", None) or [])]
    if platforms:
        requirements = list(requirements) + [f"os:{','.join(platforms)}"]
    return check_requirements(requirements)


def environment_report() -> dict[str, Any]:
    """Descreve o ambiente de execução para o diagnóstico.

    Returns:
        Um dicionário com sistema, arquitetura, sessão gráfica, diretório de trabalho,
        binário do Python e variáveis de ambiente não secretas (nomes apenas).
    """
    return {
        "system": platform.system(),
        "os": _current_os(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_executable": os.path.abspath(sys.executable),
        "gui_session": _has_gui_session(),
        "display": os.environ.get("DISPLAY", ""),
        "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
        "cwd": os.getcwd(),
        "env_var_count": len(os.environ),
    }
