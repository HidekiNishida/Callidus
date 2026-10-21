"""
Arquivo: src/agent/tools/catalog.py
Nome: catalog.py
Propósito: decidir quais ferramentas o modelo recebe em cada etapa, sem estourar o contexto.
Responsabilidade: camada de aplicação — exposição de capacidades por objetivo e configuração.
Componentes: ALL_FAMILIES, EXTRA_FAMILIES, FAMILY_HINTS, enabled_families, exposed_tools, capability_summary.
Dependências: agent.tools.contracts, agent.tools.registry.
Observações: o prompt carrega uma linha por família; o detalhe de cada ferramenta vem sob demanda.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent.tools.contracts import ToolFamily
from agent.tools.registry import ToolRegistry

#: Todas as famílias conhecidas. Usada quando a configuração desliga algumas e libera o resto.
ALL_FAMILIES: frozenset[str] = frozenset(item.value for item in ToolFamily)

#: Famílias que ficam disponíveis só quando a tarefa pede por elas.
EXTRA_FAMILIES: tuple[str, ...] = (
    ToolFamily.SYSTEM.value,
    ToolFamily.DESKTOP.value,
    ToolFamily.ENGINEERING.value,
    ToolFamily.SKILL.value,
)

#: Palavras que ligam um pedido às famílias extras. A heurística é deliberadamente
#: conservadora: sem pista clara, a etapa fica com as ferramentas do núcleo.
FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    ToolFamily.SYSTEM.value: (
        "processo", "process", "aplicativo", "app ", "abrir o programa", "instalar programa",
        "porta", "socket", "disco", "memória", "cpu", "sistema operacional", "rede", "download",
        "baixar arquivo", "hash", "checksum", "compactar", "zip", "tar", "tarefa longa",
        "segundo plano", "background", "terminar processo", "matar processo",
    ),
    ToolFamily.DESKTOP.value: (
        "tela", "screenshot", "captura de tela", "capturar a tela", "clique", "mouse", "ponteiro",
        "teclado", "digitar", "atalho", "janela", "interface gráfica", "desktop", "área de trabalho",
        "visível", "em segundo plano", "acessibilidade", "elemento da interface",
    ),
    ToolFamily.ENGINEERING.value: (
        "projeto", "dependência", "dependencias", "lint", "build", "compila", "compilar",
        "teste", "testes", "pytest", "type check", "tipagem", "cobertura", "git", "branch",
        "commit", "diff", "diagnosticar erro", "stack trace", "servidor local", "depender do projeto",
    ),
    ToolFamily.SKILL.value: (
        "skill", "habilidade", "competência", "procedimento reutilizável", "receita", "repetir esse processo",
    ),
}

#: Ferramentas sempre oferecidas: o catálogo e o pedido de detalhe.
DISCOVERY_TOOLS: tuple[str, ...] = ("tool_catalog", "tool_help")


def enabled_families(settings: Any = None) -> set[str] | None:
    """Famílias de ferramentas liberadas pela configuração.

    Args:
        settings: configuração do processo.

    Returns:
        O conjunto de famílias habilitadas, ou `None` quando todas estão liberadas.
    """
    if settings is None:
        return None
    allowed = list(getattr(settings, "tool_enabled_families", []) or [])
    disabled = {str(item) for item in (getattr(settings, "tool_disabled_families", []) or [])}
    if not allowed:
        return None if not disabled else set(ALL_FAMILIES) - disabled
    return {str(item) for item in allowed} - disabled


def families_for_objective(objective: str) -> set[str]:
    """Famílias extras sugeridas pelo texto do pedido.

    Args:
        objective: objetivo da etapa.

    Returns:
        O conjunto de famílias sugeridas.
    """
    text = (objective or "").lower()
    found: set[str] = set()
    for family, hints in FAMILY_HINTS.items():
        if any(hint in text for hint in hints):
            found.add(family)
    return found


def exposed_tools(
    registry: ToolRegistry,
    *,
    objective: str = "",
    base: Iterable[str] = (),
    settings: Any = None,
) -> tuple[str, ...]:
    """Ferramentas oferecidas ao modelo em uma etapa.

    O núcleo (arquivos, comandos, memória) vem sempre. As famílias extras entram quando
    o pedido aponta para elas e a configuração as libera. O catálogo e o pedido de
    detalhe acompanham qualquer etapa, para que o modelo descubra o resto sob demanda.

    Args:
        registry: registro de ferramentas.
        objective: objetivo da etapa.
        base: ferramentas do núcleo jáLiberadas para a etapa.
        settings: configuração do processo.

    Returns:
        A tupla de identificadores expostos.
    """
    allowed = enabled_families(settings)
    wanted = families_for_objective(objective)
    if allowed is not None:
        wanted &= allowed
    ids: list[str] = [item for item in base]
    seen = set(ids)
    for family in sorted(wanted):
        for spec in registry.specs_of_family(family):
            if spec.id not in seen:
                seen.add(spec.id)
                ids.append(spec.id)
    for tool_id in DISCOVERY_TOOLS:
        if tool_id in registry._specs and tool_id not in seen:
            seen.add(tool_id)
            ids.append(tool_id)
    return tuple(ids)


def capability_summary(registry: ToolRegistry, tool_ids: Iterable[str]) -> str:
    """Resumo compacto das capacidades expostas, para o prompt.

    O texto lista uma linha por família — não uma linha por ferramenta — e aponta para
    `tool_catalog` e `tool_help`, que carregam o detalhe sob demanda.

    Args:
        registry: registro de ferramentas.
        tool_ids: ferramentas expostas na etapa.

    Returns:
        O resumo em texto; string vazia quando nada além do núcleo foi exposto.
    """
    families: dict[str, list[str]] = {}
    for tool_id in tool_ids:
        try:
            spec = registry.get_spec(tool_id)
        except KeyError:
            continue
        if spec.family in EXTRA_FAMILIES:
            families.setdefault(spec.family, []).append(spec.id)
    if not families:
        return ""
    lines = ["Capacidades extras desta etapa (use os ids exatos; tool_catalog lista, tool_help detalha):"]
    labels = {
        ToolFamily.SYSTEM.value: "sistema e aplicativos",
        ToolFamily.DESKTOP.value: "desktop (tela, mouse, teclado)",
        ToolFamily.ENGINEERING.value: "engenharia (projeto, git, lint, testes)",
        ToolFamily.SKILL.value: "skills (ciclo de vida)",
    }
    for family in sorted(families):
        lines.append(f"- {labels.get(family, family)}: " + ", ".join(sorted(families[family])))
    return "\n".join(lines)
