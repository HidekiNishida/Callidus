# src/agent/services/attachments.py — texto, imagem e documento colados no chat
from __future__ import annotations

import base64
import re
from pathlib import Path

from agent.brand import ATTACHMENTS_DIR, LEGACY_ATTACHMENTS_DIR
from agent.security.paths import PathSecurityError, resolve_under_root

MAX_ATTACHMENTS = 8
MAX_TEXT_CHARS = 1_000_000
MAX_BYTES = 8 * 1024 * 1024
NOTE_HEADER = "Anexos do usuário:"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str, fallback: str) -> str:
    base = Path(name or "").name
    base = _SAFE.sub("-", base).strip(".-") or fallback
    return base[:80]


def _attachments_folder(project_root: str, task_id: str) -> str:
    """Pasta de anexos da tarefa. Mantém a pasta legada quando ela já tem arquivos,
    para não quebrar referências de anexos criados antes da mudança de marca."""
    legacy = f"{LEGACY_ATTACHMENTS_DIR}/anexos/{task_id}"
    current = f"{ATTACHMENTS_DIR}/anexos/{task_id}"
    try:
        legacy_abs = resolve_under_root(project_root, legacy)
    except PathSecurityError:
        return current
    if legacy_abs.is_dir() and any(legacy_abs.iterdir()):
        return legacy
    return current


def materialize_attachments(project_root: str, task_id: str, items: list) -> list[dict]:
    """Grava os anexos em `.callidus/anexos/` e devolve só referências, sem o conteúdo."""
    if not isinstance(items, list) or not items:
        return []
    if len(items) > MAX_ATTACHMENTS:
        raise ValueError(f"no máximo {MAX_ATTACHMENTS} anexos")
    folder_rel = _attachments_folder(project_root, task_id)
    try:
        folder = resolve_under_root(project_root, folder_rel)
    except PathSecurityError as exc:
        raise ValueError(str(exc)) from exc
    folder.mkdir(parents=True, exist_ok=True)
    refs: list[dict] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError("anexo inválido")
        kind = str(item.get("kind") or "file")
        if kind not in {"text", "image", "file"}:
            kind = "file"
        mime = str(item.get("mime") or "application/octet-stream")[:120]
        name = _safe_name(str(item.get("name") or ""), f"anexo-{index}")
        content = item.get("content")
        encoded = item.get("content_base64")
        if isinstance(content, str) and content and not encoded:
            if len(content) > MAX_TEXT_CHARS:
                raise ValueError(f"{name} excede o limite de texto")
            data = content.encode("utf-8")
            if kind == "file":
                kind = "text"
        elif isinstance(encoded, str) and encoded:
            payload = encoded.split(",", 1)[1] if encoded.startswith("data:") and "," in encoded else encoded
            try:
                data = base64.b64decode(payload, validate=False)
            except Exception as exc:
                raise ValueError(f"base64 inválido em {name}") from exc
        else:
            raise ValueError(f"anexo sem conteúdo: {name}")
        if len(data) > MAX_BYTES:
            raise ValueError(f"{name} excede 8 MB")
        rel = f"{folder_rel}/{index:02d}-{name}"
        try:
            dest = resolve_under_root(project_root, rel)
        except PathSecurityError as exc:
            raise ValueError(str(exc)) from exc
        dest.write_bytes(data)
        refs.append({"name": name, "kind": kind, "mime": mime, "path": rel, "bytes": len(data)})
    return refs


def attachment_note(refs: list[dict]) -> str:
    lines = [
        NOTE_HEADER,
        "Arquivos gravados no projeto. Leia com read_file. Não trate como código do produto até o pedido pedir.",
    ]
    for ref in refs:
        lines.append(f"- {ref['kind']} {ref['name']} → {ref['path']} ({ref['bytes']} bytes)")
    return "\n".join(lines)
