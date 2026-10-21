"""
Arquivo: src/agent/tools/desktop_tools.py
Nome: desktop_tools.py
Propósito: expor ao agente a automação de desktop: tela, entrada, janelas e screenshots.
Responsabilidade: camada de apresentação — handlers das ferramentas de interface gráfica.
Componentes: register_all e os handlers de tela, captura, clique, digitação, tecla, rolagem e janelas.
Dependências: agent.desktop, agent.tools.registry, agent.tools.contracts.
Observações: a automação gráfica exige sessão gráfica; as ferramentas dizem quando ela falta.
"""
from __future__ import annotations

from agent.desktop.accessibility import click_named, list_elements, wait_for
from agent.desktop.capabilities import capture_screenshot, screen_info
from agent.desktop.input import click, drag, press_key, scroll, type_text
from agent.desktop.windows import list_windows
from agent.system.adapters import session_kind
from agent.tools.contracts import ExecutionMode, ToolFamily, ToolRisk
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec


async def _screen(ctx: ToolContext, args: dict) -> dict:
    """Informa a geometria da tela e as limitações da sessão.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (não usados).

    Returns:
        Um dicionário com a geometria e a sessão.
    """
    info = screen_info()
    info["session"] = session_kind()
    return info


async def _screenshot(ctx: ToolContext, args: dict) -> dict:
    """Captura a tela inteira ou uma região.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path` opcional, `region` opcional).

    Returns:
        Um dicionário com o caminho da imagem.
    """
    region = args.get("region")
    if isinstance(region, dict):
        try:
            region = {key: int(region[key]) for key in ("x", "y", "width", "height")}
        except (KeyError, TypeError, ValueError):
            return {"success": False, "error": "region precisa de x, y, width e height inteiros"}
    else:
        region = None
    return capture_screenshot(path=args.get("path"), region=region)


async def _click(ctx: ToolContext, args: dict) -> dict:
    """Clica em um ponto da tela.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`x`, `y`, `double`, `button`).

    Returns:
        Um dicionário com o resultado da ação.
    """
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
    except (TypeError, ValueError):
        return {"success": False, "error": "informe x e y inteiros"}
    return click(x, y, double=bool(args.get("double")), button=str(args.get("button") or "left"))


async def _drag(ctx: ToolContext, args: dict) -> dict:
    """Arrasta o ponteiro de um ponto a outro.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`x1`, `y1`, `x2`, `y2`).

    Returns:
        Um dicionário com o resultado da ação.
    """
    try:
        x1, y1, x2, y2 = (int(args.get(key)) for key in ("x1", "y1", "x2", "y2"))
    except (TypeError, ValueError):
        return {"success": False, "error": "informe x1, y1, x2 e y2 inteiros"}
    return drag(x1, y1, x2, y2)


async def _type(ctx: ToolContext, args: dict) -> dict:
    """Digita um texto na janela em foco.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`text`).

    Returns:
        Um dicionário com o resultado da ação.
    """
    text = args.get("text")
    if text is None:
        return {"success": False, "error": "informe o texto"}
    return type_text(str(text))


async def _key(ctx: ToolContext, args: dict) -> dict:
    """Pressiona uma tecla ou um atalho.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`key`).

    Returns:
        Um dicionário com o resultado da ação.
    """
    key = str(args.get("key") or "")
    if not key:
        return {"success": False, "error": "informe a tecla"}
    return press_key(key)


async def _scroll(ctx: ToolContext, args: dict) -> dict:
    """Rola a tela.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`amount`, `horizontal`).

    Returns:
        Um dicionário com o resultado da ação.
    """
    try:
        amount = int(args.get("amount") or 3)
    except (TypeError, ValueError):
        return {"success": False, "error": "informe 'amount' inteiro"}
    return scroll(amount, horizontal=bool(args.get("horizontal")))


async def _elements(ctx: ToolContext, args: dict) -> dict:
    """Lista os elementos da janela pela árvore de acessibilidade.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`app` opcional, `limit` opcional).

    Returns:
        Um dicionário com os elementos, ou o diagnóstico da plataforma.
    """
    del ctx
    limit = args.get("limit") or 40
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 40
    return list_elements(args.get("app"), limit=limit)


async def _wait(ctx: ToolContext, args: dict) -> dict:
    """Espera uma janela ou um elemento aparecer.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`title`, `name`, `timeout`).

    Returns:
        O que foi encontrado, ou o tempo esgotado.
    """
    del ctx
    try:
        timeout = float(args.get("timeout") or 8)
    except (TypeError, ValueError):
        timeout = 8
    return wait_for(title=str(args.get("title") or ""), name=str(args.get("name") or ""), timeout=timeout)


async def _click_element(ctx: ToolContext, args: dict) -> dict:
    """Clica em um elemento localizado pelo nome na árvore de acessibilidade.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`, `app`, `button`).

    Returns:
        O resultado do clique, ou o motivo da recusa.
    """
    del ctx
    return click_named(str(args.get("name") or ""), app=args.get("app"), button=str(args.get("button") or "left"))


async def _windows(ctx: ToolContext, args: dict) -> dict:
    """Lista as janelas visíveis da sessão gráfica.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`match` opcional, `limit` opcional).

    Returns:
        Um dicionário com a lista de janelas.
    """
    return list_windows(match=args.get("match"), limit=int(args.get("limit") or 50))


def register_all(registry: ToolRegistry) -> None:
    """Registra as ferramentas de automação de desktop.

    As ferramentas de desktop exigem sessão gráfica ativa; o registro marca isso com
    o requisito `session:gui`, de modo que a indisponibilidade seja explicada em vez
    de virar erro genérico.

    Args:
        registry: registro onde as ferramentas são cadastradas.
    """
    specs = [
        ToolSpec(
            id="desktop_screen",
            description="Geometria da tela, monitores e limitações da sessão",
            input_schema={},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'bounds'",
        ),
        ToolSpec(
            id="desktop_screenshot",
            description="Captura a tela ou uma região em PNG",
            input_schema={"path": "str?", "region": "dict?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.READ.value,
            requires=["session:gui"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'bytes'",
        ),
        ToolSpec(
            id="desktop_click",
            description="Clica em coordenadas da tela",
            input_schema={"x": "int", "y": "int", "double": "bool?", "button": "str?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.mouse"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="tire um screenshot depois da ação",
        ),
        ToolSpec(
            id="desktop_drag",
            description="Arrasta o ponteiro entre dois pontos",
            input_schema={"x1": "int", "y1": "int", "x2": "int", "y2": "int"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.mouse"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="tire um screenshot depois da ação",
        ),
        ToolSpec(
            id="desktop_type",
            description="Digita texto na janela em foco",
            input_schema={"text": "str"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.keyboard"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="tire um screenshot depois da ação",
        ),
        ToolSpec(
            id="desktop_key",
            description="Pressiona uma tecla ou atalho (cmd+s, ctrl+shift+p, enter)",
            input_schema={"key": "str"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.keyboard"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="tire um screenshot depois da ação",
        ),
        ToolSpec(
            id="desktop_scroll",
            description="Rola a tela",
            input_schema={"amount": "int?", "horizontal": "bool?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.mouse"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="tire um screenshot depois da ação",
        ),
        ToolSpec(
            id="desktop_windows",
            description="Lista janelas visíveis, títulos e aplicativos",
            input_schema={"match": "str?", "limit": "int?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.READ.value,
            requires=["session:gui"],
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="desktop_elements",
            description="Lista elementos da janela pela árvore de acessibilidade (nome, papel, retângulo)",
            input_schema={"app": "str?", "limit": "int?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.READ.value,
            requires=["session:gui"],
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count' e o mecanismo 'accessibility'",
        ),
        ToolSpec(
            id="desktop_wait",
            description="Espera uma janela pelo título ou um elemento pelo nome",
            input_schema={"title": "str?", "name": "str?", "timeout": "float?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.READ.value,
            requires=["session:gui"],
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'matched'",
        ),
        ToolSpec(
            id="desktop_click_element",
            description="Clica em um elemento pelo nome, relendo a geometria na hora",
            input_schema={"name": "str", "app": "str?", "button": "str?"},
            family=ToolFamily.DESKTOP.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            requires=["session:gui"],
            permissions=["input.mouse"],
            side_effects=True,
            execution=ExecutionMode.INTERACTIVE.value,
            verify="liste os elementos de novo e confira o estado",
        ),
    ]
    handlers = {
        "desktop_screen": _screen,
        "desktop_screenshot": _screenshot,
        "desktop_click": _click,
        "desktop_drag": _drag,
        "desktop_type": _type,
        "desktop_key": _key,
        "desktop_scroll": _scroll,
        "desktop_windows": _windows,
        "desktop_elements": _elements,
        "desktop_wait": _wait,
        "desktop_click_element": _click_element,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])


__all__ = ["register_all"]
