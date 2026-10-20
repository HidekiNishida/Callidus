"""
Arquivo: src/agent/util/json_parse.py
Nome: json_parse.py
Propósito: interpretar a resposta JSON do modelo, com recuperação limitada quando há ruído ao redor.
Responsabilidade: camada de aplicação — extração tolerante do objeto JSON pedido.
Componentes: parse_json_object.
Dependências: json, re.
Observações: a recuperação é mínima (remove `<think>` e extrai o primeiro objeto); não corrige JSON malformado.
"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extrai o objeto JSON de uma resposta do modelo.

    Args:
        text: resposta bruta do modelo.

    Returns:
        Tupla com o objeto interpretado e `None` quando tudo deu certo, ou `(None, motivo)`
        quando a resposta está vazia, não é objeto ou é inválida.
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if not text:
        return None, "resposta vazia"
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, None
        return None, "JSON não é objeto"
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data, None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, "JSON inválido"
