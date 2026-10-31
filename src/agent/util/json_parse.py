"""
Arquivo: src/agent/util/json_parse.py
Nome: json_parse.py
Propósito: interpretar a resposta JSON do modelo, com recuperação limitada quando há ruído ao redor.
Responsabilidade: camada de aplicação — extração tolerante do objeto JSON pedido.
Componentes: parse_json_object, write_payloads, pick_write_payload.
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


_WRITE_TOOLS = {"write_file", "edit_file"}


def write_payloads(text: str) -> list[dict[str, Any]]:
    """Escritas contidas numa resposta com vários objetos JSON seguidos.

    Aceita o formato pedido (`{"path": ..., "content": ...}` ou com `old_string`/`new_string`) e o
    formato de chamada que modelos pequenos usam quando respondem sem raciocínio
    (`{"name": "write_file", "arguments": {"path": ...}}`), um após o outro.

    Args:
        text: resposta bruta do modelo.

    Returns:
        Os objetos de escrita na ordem em que aparecem (cada um com `path`); objetos sem caminho,
        leituras e um objeto final cortado ficam de fora.
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", text or "")
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    pos = 0
    while True:
        start = text.find("{", pos)
        if start < 0:
            break
        try:
            data, pos = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            break
        if not isinstance(data, dict):
            continue
        if data.get("name") in _WRITE_TOOLS and isinstance(data.get("arguments"), dict):
            data = data["arguments"]
        if isinstance(data.get("path"), str) and data["path"].strip():
            found.append(data)
    return found


def pick_write_payload(payloads: list[dict[str, Any]], hint: str) -> dict[str, Any] | None:
    """Escolhe a escrita que pertence à etapa.

    Args:
        payloads: escritas encontradas por `write_payloads`.
        hint: título e objetivo da etapa (o arquivo citado decide).

    Returns:
        A última escrita do arquivo citado na etapa; sem citação, a única escrita quando todas são do
        mesmo arquivo; senão `None` (ambíguo: melhor reprovar do que gravar o arquivo errado).
    """
    if not payloads:
        return None
    low = (hint or "").lower()
    named = [p for p in payloads if p["path"].replace("\\", "/").rsplit("/", 1)[-1].lower() in low]
    if named:
        return named[-1]
    if len({p["path"] for p in payloads}) == 1:
        return payloads[-1]
    return None
