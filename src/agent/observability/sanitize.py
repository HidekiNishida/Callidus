"""
Arquivo: src/agent/observability/sanitize.py
Nome: sanitize.py
Propósito: remover segredos e limitar o tamanho do conteúdo que vai para os eventos.
Responsabilidade: camada de aplicação — sanitização e truncamento dos payloads publicados.
Componentes: REDACTED, is_sensitive_path, redact_text, truncate, sanitize.
Dependências: re, pathlib.
Observações: a sanitização é aplicada a todo evento persistido ou efêmero antes da publicação.
"""
from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

REDACTED = "[redigido]"

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth",
        "authorization",
        "private_key",
        "cookie",
        "set-cookie",
    }
)
# Chaves cujo valor inteiro não interessa ao acompanhamento e pode carregar segredos (ambiente do processo).
_DROPPED_KEYS = frozenset({"env", "environ", "environment", "headers"})

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
        "-----PRIVATE KEY " + REDACTED + "-----",
    ),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), REDACTED),
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)[A-Z0-9_]*)"
            r"(\s*[:=]\s*|\"\s*:\s*\")"
            # Não redige números (contagens como `max_tokens=4096`), referências de código nem literais.
            r"(?!\[redigido\]|\d+\b|(?:os\.|getenv|environ|settings\.|self\.|config\.|request\.|None\b|null\b"
            r"|True\b|False\b|true\b|false\b))"
            r"([^\s\"',;]{4,})"
        ),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"(?i)(://[^:/\s@]+:)[^@/\s]+@"), r"\1" + REDACTED + "@"),
)

_SENSITIVE_NAMES = frozenset({".env", ".netrc", ".pgpass", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


def is_sensitive_path(path: str | None) -> bool:
    """Arquivos cujo conteúdo (diff, trecho) não deve sair em eventos; o caminho pode."""
    if not path:
        return False
    name = PurePath(path).name.lower()
    if name in _SENSITIVE_NAMES or name.startswith(".env."):
        return True
    if "credential" in name or "secret" in name:
        return True
    return name.endswith(_SENSITIVE_SUFFIXES)


def redact_text(text: str) -> str:
    """Substitui segredos reconhecíveis no texto por um marcador.

    Args:
        text: texto a inspecionar.

    Returns:
        O texto com as credenciais encontradas substituídas por `[redigido]`.
    """
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def truncate(text: str, limit: int) -> str:
    """Corta o texto ao limite, preservando o início e o fim e marcando o trecho omitido.

    Args:
        text: texto original.
        limit: tamanho máximo do resultado; valores não positivos desativam o corte.

    Returns:
        O texto truncado, ou o original quando já cabe no limite.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    est_marker = f"\n…[{len(text) - limit} caracteres omitidos]…\n"
    if limit <= len(est_marker) + 4:
        return text[:limit]
    budget = limit - len(est_marker)
    omitted = len(text) - budget
    marker = f"\n…[{omitted} caracteres omitidos]…\n"
    budget = limit - len(marker)
    head = int(budget * 0.4)
    tail = budget - head
    return f"{text[:head]}{marker}{text[-tail:]}" if tail > 0 else f"{text[:head]}{marker}"


def sanitize(value: Any, *, limit: int = 20_000, _depth: int = 0) -> Any:
    """Copia `value` redigindo segredos e truncando textos; não muda tipos JSON básicos."""
    if _depth > 12:
        return "[estrutura profunda omitida]"
    if isinstance(value, str):
        return truncate(redact_text(value), limit)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            low = key.lower()
            if low in _DROPPED_KEYS and isinstance(v, (dict, list)):
                out[key] = "[omitido]"
            elif low in _SECRET_KEYS and v not in (None, "", 0, False):
                out[key] = REDACTED
            else:
                out[key] = sanitize(v, limit=limit, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize(v, limit=limit, _depth=_depth + 1) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return truncate(redact_text(str(value)), limit)
