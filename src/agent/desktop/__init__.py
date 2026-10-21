"""
Arquivo: src/agent/desktop/__init__.py
Nome: __init__.py
Propósito: expor a automação de desktop (tela, entrada, janelas) com uma interface única.
Responsabilidade: camada de infraestrutura — ponto de entrada estável para o agente.
Componentes: reexports de `accessibility`, `capabilities`, `input` e `windows`.
Dependências: agent.desktop.*.
Observações: cada função informa a limitação da plataforma quando a operação não é possível.
"""
from __future__ import annotations

from agent.desktop.accessibility import click_named, list_elements, wait_for
from agent.desktop.capabilities import capture_screenshot, screen_info
from agent.desktop.input import click, drag, press_key, scroll, type_text
from agent.desktop.windows import list_windows

__all__ = [
    "capture_screenshot",
    "click",
    "click_named",
    "drag",
    "list_elements",
    "list_windows",
    "press_key",
    "screen_info",
    "scroll",
    "type_text",
    "wait_for",
]
