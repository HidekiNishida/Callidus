"""
Arquivo: src/agent/orchestrator/execution/guards.py
Nome: guards.py
Propósito: decidir o que a etapa pode fazer com as ferramentas e com a resposta do modelo.
Responsabilidade: camada de aplicação — permissões de escrita e usabilidade do payload do modelo.
Componentes: operation_tools_for, write_refusal_reason, payload_is_usable.
Dependências: agent.orchestrator.strategy (reconhece arquivo de teste), agent.util.json_parse.
Observações: a decisão vem do pedido (permissão), nunca do modelo — o modelo não pode ampliar a própria permissão.
"""

from __future__ import annotations

from typing import Any

from agent.orchestrator.strategy import looks_like_test_file

WRITE_TOOLS = ("write_file", "edit_file", "move_file")


def operation_tools_for(
    meta: dict,
    *,
    registry: Any = None,
    settings: Any = None,
    objective: str = "",
) -> tuple[str, ...]:
    """Ferramentas da etapa: sem `write_file`/`edit_file` quando o pedido é somente leitura.

    "Não altere nenhum arquivo do projeto" vira **permissão**, não apenas instrução: o modelo
    recebe as ferramentas de leitura e o caminho que escreve no disco recusa a alteração.

    Quando há registro e objetivo, as famílias extras (sistema, desktop, engenharia, skills)
    entram no conjunto — a exposição vem do pedido e da configuração, nunca do modelo.

    Args:
        meta: metadados da etapa (`read_only` indica pedido somente leitura).
        registry: registro de ferramentas, quando disponível.
        settings: configuração do processo, para filtrar as famílias liberadas.
        objective: objetivo da etapa, usado para reconhecer as famílias pedidas.

    Returns:
        Os identificadores de ferramenta liberados para a etapa.
    """
    from agent.orchestrator.tool_loop import INSPECTION_TOOLS, OPERATION_TOOLS

    if (meta or {}).get("read_only"):
        base = INSPECTION_TOOLS
    else:
        base = OPERATION_TOOLS
    if registry is None:
        return base
    from agent.tools.catalog import exposed_tools

    return exposed_tools(registry, objective=objective, base=base, settings=settings)


def write_refusal_reason(meta: dict, tool_name: str, path: str | None) -> str | None:
    """Por que esta escrita não pode acontecer (ou `None`, quando pode).

    Duas proteções, ambas do pedido e não do modelo:

    - **Somente leitura**: o pedido proíbe alterar o projeto.
    - **Régua protegida**: os arquivos de teste são o critério da medição. Alterá-los para a
      medição passar é trocar o critério, não resolver o problema — a menos que o pedido
      mande mexer nos testes.

    Args:
        meta: metadados da etapa (`read_only`, `protect_tests`).
        tool_name: identificador da ferramenta que pretende escrever.
        path: caminho alvo da escrita, quando houver.

    Returns:
        O motivo da recusa, ou `None` quando a escrita é permitida.
    """
    if tool_name not in WRITE_TOOLS:
        return None
    if (meta or {}).get("read_only"):
        return "a etapa é somente leitura: o pedido proíbe alterar arquivos"
    if (meta or {}).get("protect_tests") and path and looks_like_test_file(str(path)):
        return f"o pedido não pede para alterar os testes: «{path}» é o critério da medição"
    return None


def payload_is_usable(content: str) -> bool:
    """A resposta do modelo já é o JSON que a etapa espera (criar ou editar)?

    Args:
        content: texto bruto devolvido pelo modelo.

    Returns:
        `True` quando o texto contém um objeto com `path` e o conteúdo a escrever.
    """
    from agent.util.json_parse import parse_json_object

    data, err = parse_json_object(content or "")
    if err or not isinstance(data, dict):
        return False
    if not isinstance(data.get("path"), str) or not data.get("path").strip():
        return False
    return bool(data.get("content") or data.get("new_string"))


def evidence_state(passed: bool | None, blocked: bool = False) -> str:
    """Estado gravado na evidência; `desatualizado` é marcado depois, por `reopen_verification_gaps`.

    Args:
        passed: veredito do verificador (`True`, `False` ou `None` para inconclusivo).
        blocked: `True` quando a verificação foi bloqueada por ambiente.

    Returns:
        O rótulo persistido na evidência.
    """
    if blocked:
        return "bloqueado"
    return {True: "aprovado", False: "reprovado"}.get(passed, "inconclusivo")


def compact_inspection(
    inspections: list[dict[str, Any]], max_items: int = 6, max_chars: int = 900
) -> list[dict]:
    """Inspeção da tentativa, enxuta: o que foi lido e um trecho do conteúdo.

    Args:
        inspections: registros de leitura feitos pelas ferramentas na tentativa.
        max_items: quantas leituras recentes manter.
        max_chars: tamanho máximo do trecho de conteúdo guardado.

    Returns:
        Lista de dicionários `{"path", "content"}` pronta para o metadado da tarefa.
    """
    out: list[dict[str, Any]] = []
    for item in inspections[-max_items:]:
        path = item.get("path")
        if not path:
            continue
        content = str(item.get("content") or "")[:max_chars]
        out.append({"path": path, "content": content})
    return out
