# src/agent/util/json_parse.py — parse JSON com recuperação limitada
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    text = text.strip()
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
