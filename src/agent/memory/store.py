# src/agent/memory/store.py — resumo na criação e recorte na leitura
from __future__ import annotations

import re

_REMEMBER = re.compile(
    r"(?i)\b(lembre(?:-se)?(?:\s+que)?|memorize|guarde(?:\s+que)?|remember(?:\s+that)?|recuerda(?:\s+que)?|anote(?:\s+que)?|não esqueca|nao esqueca)\b[:\s,-]*"
)
_SPLIT = re.compile(r"\n\s*\n|(?<=[.!?])\s+")


def summarize_text(text: str, limit: int = 320) -> str:
    """Resumo curto. O texto completo continua guardado em outro campo."""
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    parts = [part.strip() for part in _SPLIT.split(raw) if part.strip()]
    chosen: list[str] = []
    used = 0
    for part in parts:
        if chosen and used + len(part) + 1 > limit:
            break
        chosen.append(part)
        used += len(part) + 1
    summary = " ".join(chosen).strip() or raw[:limit].rstrip()
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip() + "…"
    return summary


def decompose_for_use(text: str, objective: str, *, budget: int = 480) -> list[str]:
    """Quebra a memória e devolve só os trechos que conversam com o objetivo."""
    chunks = [chunk.strip() for chunk in _SPLIT.split(text or "") if chunk.strip()]
    if not chunks:
        return []
    words = {token.lower() for token in re.findall(r"\w{4,}", objective or "")}
    ranked = []
    for index, chunk in enumerate(chunks):
        tokens = {token.lower() for token in re.findall(r"\w{4,}", chunk)}
        ranked.append((len(words & tokens), -index, chunk))
    ranked.sort(reverse=True)
    relevant = [chunk for score, _, chunk in ranked if score > 0]
    source = relevant or [summarize_text(text, limit=budget)]
    picked: list[str] = []
    used = 0
    for chunk in source:
        if picked and used + len(chunk) > budget:
            break
        piece = chunk[:budget]
        picked.append(piece)
        used += len(piece)
    return picked


def structure_memory(text: str) -> dict:
    """Índice curto: resumo, fatos e tópicos. O texto completo fica de fora."""
    raw = (text or "").strip()
    facts: list[str] = []
    for chunk in _SPLIT.split(raw):
        piece = chunk.strip()
        if not piece:
            continue
        if len(piece) > 180:
            piece = piece[:179].rstrip() + "…"
        facts.append(piece)
        if len(facts) >= 8:
            break
    topics: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"\w{5,}", raw.lower()):
        if token in seen:
            continue
        seen.add(token)
        topics.append(token)
        if len(topics) >= 6:
            break
    return {"summary": summarize_text(raw), "facts": facts, "topics": topics}


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"\w{4,}", text or "")}


def choose_memory_index(rows: list[dict], objective: str, *, limit: int = 4) -> list[dict]:
    """Escolhe pelo índice. O texto completo nem entra nesta etapa."""
    wanted = _tokens(objective)
    scored: list[tuple[int, int, dict]] = []
    for index, row in enumerate(rows):
        blob = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("summary") or ""),
                " ".join(row.get("topics") or []),
                " ".join((row.get("facts") or [])[:3]),
            ]
        )
        scored.append((len(wanted & _tokens(blob)), -index, row))
    scored.sort(reverse=True)
    chosen = [row for score, _, row in scored if score > 0][:limit]
    if not any(row.get("scope") == "project" for row in chosen):
        project = next((row for row in rows if row.get("scope") == "project"), None)
        if project is not None:
            chosen = [project, *chosen][:limit]
    return chosen


def fragments_for_prompt(summary: str, content: str, objective: str, *, budget: int = 480) -> str:
    """Usa o resumo e, quando couber, os pedaços relevantes do texto completo."""
    pieces = decompose_for_use(content, objective, budget=budget)
    head = (summary or "").strip()
    body = "\n".join(pieces).strip()
    if head and head not in body:
        text = f"{head}\n{body}".strip()
    else:
        text = body or head
    return text[:budget]


def extract_memory_request(text: str) -> tuple[str, str] | None:
    """Se a pessoa pediu para lembrar, devolve (escopo, fato)."""
    match = _REMEMBER.search(text or "")
    if not match:
        return None
    fact = (text or "")[match.end() :].strip() or (text or "").strip()
    low = (text or "").lower()
    scope = "project" if any(word in low for word in ("projeto", "project", "sempre", "siempre", "always")) else "conversation"
    return scope, fact
