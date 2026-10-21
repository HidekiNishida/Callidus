"""
Arquivo: src/agent/tools/arguments.py
Nome: arguments.py
Propósito: validar os argumentos de uma ferramenta contra o esquema declarado no registro.
Responsabilidade: camada de infraestrutura — conferência de presença e de tipo antes da execução.
Componentes: validate_arguments.
Dependências: nenhuma além da biblioteca padrão.
Observações: aceita o atalho textual (`path: str?`) e o JSON Schema usado pelas automações.
"""
from __future__ import annotations

from typing import Any

_SCALARS = {
    "str": lambda value: isinstance(value, str),
    "int": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "bool": lambda value: isinstance(value, bool),
    "float": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "dict": lambda value: isinstance(value, dict),
    "list": lambda value: isinstance(value, list),
}

_JSON_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
}


def validate_arguments(schema: dict[str, Any] | None, args: dict[str, Any] | None) -> str | None:
    """Confere os argumentos contra o esquema da ferramenta.

    Campos a mais são aceitos: o modelo às vezes inclui contexto que o handler ignora.
    Campo obrigatório ausente ou com tipo errado devolve a mensagem do erro. Um esquema
    vazio ou de formato desconhecido não bloqueia a execução.

    Args:
        schema: esquema declarado em `ToolSpec.input_schema`.
        args: argumentos recebidos do modelo.

    Returns:
        A mensagem do erro, ou `None` quando os argumentos são aceitos.
    """
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "os argumentos devem ser um objeto"
    if not schema:
        return None
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        return _validate_json_schema(schema, args)
    if schema and all(isinstance(value, str) for value in schema.values()):
        return _validate_shorthand(schema, args)
    return None


def _validate_shorthand(schema: dict[str, str], args: dict[str, Any]) -> str | None:
    """Valida o atalho `nome: tipo` usado pela maioria das ferramentas.

    Args:
        schema: mapa de nome para tipo (`str`, `int?`, `str|list[str]`, `project|conversation`).
        args: argumentos recebidos.

    Returns:
        A mensagem do erro, ou `None`.
    """
    for name, spec in schema.items():
        optional = spec.endswith("?")
        body = spec[:-1] if optional else spec
        present = name in args and args[name] is not None
        if not present:
            if optional:
                continue
            return f"argumento obrigatório ausente: {name}"
        if not _matches_union(body, args[name]):
            return f"argumento {name} deve ser {body}"
    return None


def _validate_json_schema(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Valida um JSON Schema de objeto, no nível das propriedades declaradas.

    Args:
        schema: esquema com `properties` e `required`.
        args: argumentos recebidos.

    Returns:
        A mensagem do erro, ou `None`.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for name in required:
        if name not in args or args[name] is None:
            return f"argumento obrigatório ausente: {name}"
    for name, prop in properties.items():
        if name not in args or args[name] is None:
            continue
        if not isinstance(prop, dict):
            continue
        enum = prop.get("enum")
        if isinstance(enum, list) and args[name] not in enum:
            options = ", ".join(str(item) for item in enum)
            return f"argumento {name} deve ser um de: {options}"
        if not _matches_json_property(prop, args[name]):
            expected = prop.get("type") or "valor"
            return f"argumento {name} deve ser {expected}"
    return None


def _matches_union(body: str, value: Any) -> bool:
    """Indica se o valor casa com algum dos tipos unidos por `|`.

    Args:
        body: tipos alternativos, sem o sufixo opcional.
        value: valor recebido.

    Returns:
        `True` quando pelo menos uma alternativa aceita o valor.
    """
    return any(_matches_atom(atom.strip(), value) for atom in body.split("|") if atom.strip())


def _matches_atom(atom: str, value: Any) -> bool:
    """Indica se o valor casa com um tipo ou um literal.

    Args:
        atom: tipo (`str`, `list[str]`) ou literal (`project`).
        value: valor recebido.

    Returns:
        `True` quando o valor é aceito.
    """
    if atom.startswith("list[") and atom.endswith("]"):
        inner = atom[5:-1]
        return isinstance(value, list) and all(_matches_atom(inner, item) for item in value)
    checker = _SCALARS.get(atom)
    if checker is not None:
        return checker(value)
    return value == atom


def _matches_json_property(prop: dict[str, Any], value: Any) -> bool:
    """Indica se o valor casa com uma propriedade de JSON Schema.

    Args:
        prop: propriedade, com `type`, `enum` e `items` quando houver.
        value: valor recebido.

    Returns:
        `True` quando o valor é aceito.
    """
    enum = prop.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    kind = prop.get("type")
    if kind is None:
        return True
    mapped = _JSON_TYPES.get(str(kind))
    if mapped is None:
        return True
    if mapped == "list":
        if not isinstance(value, list):
            return False
        items = prop.get("items")
        if isinstance(items, dict):
            return all(_matches_json_property(items, item) for item in value)
        return True
    return _matches_atom(mapped, value)
