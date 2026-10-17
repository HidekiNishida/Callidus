# src/agent/orchestrator/closing.py — verificação e resposta final fecham o plano
from __future__ import annotations

import re
from datetime import datetime

from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec

_WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def local_now_line() -> str:
    now = datetime.now().astimezone()
    return (
        f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year}, "
        f"{now:%H:%M}"
    )

_PATH = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}|[\w.-]+\.(?:py|md|js|css|html|json|toml|ts|tsx)")


def ensure_closing_stages(plan: DecompositionResult) -> DecompositionResult:
    """Garante verificação e uma resposta final depois das etapas de implementação."""
    subtasks = list(plan.subtasks)
    has_verify = any((item.metadata or {}).get("verification") for item in subtasks)
    has_final = any((item.metadata or {}).get("final_answer") for item in subtasks)
    last = len(subtasks) - 1
    if not has_verify:
        subtasks.append(
            SubTaskSpec(
                title="Verificar etapas",
                objective="Confirmar que as etapas anteriores terminaram antes da conclusão.",
                metadata={"verification": {"type": "stages"}},
                depends_on_indices=[last] if last >= 0 else [],
            )
        )
        last = len(subtasks) - 1
    if not has_final:
        subtasks.append(
            SubTaskSpec(
                title="Resposta final",
                objective="Escrever a conclusão para o usuário: o que foi feito, como foi verificado e as fontes.",
                metadata={"final_answer": True, "model_operation": True},
                depends_on_indices=[last] if last >= 0 else [],
            )
        )
    return DecompositionResult(subtasks=subtasks)


def compose_final_markdown(*, objective: str, stages: list[dict], model_text: str = "") -> str:
    rows = ["| Etapa | Estado |", "| --- | --- |"]
    for stage in stages:
        title = str(stage.get("title") or "etapa").replace("|", "/")
        status = str(stage.get("status") or "").replace("|", "/")
        rows.append(f"| {title} | {status} |")
    sources = []
    for stage in stages:
        for path in stage.get("sources") or []:
            if path not in sources:
                sources.append(path)
    source_lines = "\n".join(f"- `{path}`" for path in sources) or "- (nenhum arquivo citado)"
    extra = ""
    if model_text.strip():
        extra = f"\n\n### Notas do modelo\n\n{model_text.strip()[:1200]}\n"
    return (
        f"## Conclusão\n\n{objective.strip()}\n\n"
        f"Agora: {local_now_line()}.\n\n"
        f"### Etapas\n\n" + "\n".join(rows) + "\n\n"
        f"### Fontes\n\n{source_lines}"
        f"{extra}"
    )


def usable_reply(text: str) -> bool:
    """Aceita Markdown ou uma frase comum. JSON de ferramenta não é resposta."""
    body = text.strip()
    if usable_markdown(body):
        return True
    if len(body) < 8 or body.startswith("{") or body.startswith("["):
        return False
    return True


def usable_markdown(text: str) -> bool:
    body = text.strip()
    if len(body) < 40:
        return False
    if body.startswith("{") or body.startswith("["):
        return False
    markers = ("#", "\n- ", "\n* ", "| --- |", "|---|", "```")
    return any(marker in body or body.startswith(marker.strip()) for marker in markers)


def extract_sources(*chunks: str) -> list[str]:
    found: list[str] = []
    for chunk in chunks:
        for match in _PATH.findall(chunk or ""):
            if match.startswith(("a/", "b/")) or match in found:
                continue
            found.append(match)
    return found[:12]
