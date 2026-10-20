"""
Arquivo: src/agent/orchestrator/closing.py
Nome: closing.py
Propósito: verificação e resposta final fecham o plano.
Responsabilidade: camada de aplicação.
Componentes: local_now_line, ensure_closing_stages, compose_final_markdown, compose_incomplete_markdown, usable_reply, usable_markdown….
Dependências: agent.orchestrator.consolidation, agent.orchestrator.decomposition, agent.persistence.models, __future__, datetime, re….
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""

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
    """Monta a data e a hora atuais em português, no fuso do processo.

    Returns:
        Uma frase com o dia da semana, a data e a hora.
    """
    now = datetime.now().astimezone()
    return (
        f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year}, "
        f"{now:%H:%M}"
    )

_PATH = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}|[\w.-]+\.(?:py|md|js|css|html|json|toml|ts|tsx)")


def ensure_closing_stages(plan: DecompositionResult) -> DecompositionResult:
    """Garante verificação e uma resposta final depois das etapas de implementação.

    A verificação vem **antes** da resposta final: um plano que já traz a resposta final mas não
    traz verificação recebia a verificação depois dela (e dependente dela), ou seja, a conclusão
    era escrita antes de existir qualquer conferência.
    """
    subtasks = list(plan.subtasks)
    has_verify = any((item.metadata or {}).get("verification") for item in subtasks)
    has_final = any((item.metadata or {}).get("final_answer") for item in subtasks)
    last = len(subtasks) - 1
    if not has_verify:
        verify = SubTaskSpec(
            title="Verificar etapas",
            objective="Confirmar que as etapas anteriores terminaram antes da conclusão.",
            metadata={"verification": {"type": "stages"}},
        )
        if has_final:
            # A resposta final existe e está no fim: a verificação entra **antes** dela e
            # depende da última etapa de implementação (nunca da resposta final — senão as
            # duas viram dependentes uma da outra e o ciclo é cortado).
            final_index = max(
                index for index, item in enumerate(subtasks) if (item.metadata or {}).get("final_answer")
            )
            previous = final_index - 1
            verify = verify.model_copy(
                update={"depends_on_indices": [previous] if previous >= 0 else []}
            )
            subtasks.insert(final_index, verify)
        else:
            subtasks.append(verify.model_copy(update={"depends_on_indices": [last] if last >= 0 else []}))
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
    return DecompositionResult(subtasks=subtasks, warnings=list(plan.warnings))


def compose_final_markdown(*, objective: str, stages: list[dict], model_text: str = "") -> str:
    """Monta a resposta final em Markdown, com as etapas, as fontes e as notas do modelo.

    Args:
        objective: objetivo do trabalho concluído.
        stages: etapas executadas, com título, estado e fontes citadas.
        model_text: observações do modelo sobre o resultado.

    Returns:
        O texto Markdown da conclusão, incluindo o momento da entrega.
    """
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


def compose_incomplete_markdown(
    *, objective: str, pending: list[dict], reason: str, requirements: list[dict] | None = None
) -> str:
    """Mensagem de quando o trabalho parou sem cumprir tudo: pendências e, se houver, o estado de cada
    requisito (o que foi comprovado e o que não foi). Nunca afirma conclusão."""
    rows = ["| Etapa | Estado | Motivo |", "| --- | --- | --- |"]
    for item in pending:
        cells = [str(item.get(key) or "").replace("|", "/").replace("\n", " ") for key in ("title", "status", "reason")]
        rows.append(f"| {cells[0]} | {cells[1]} | {cells[2][:200]} |")
    table = "\n".join(rows) if pending else "- (nenhuma etapa pendente listada)"
    reqs = ""
    if requirements:
        lines = ["| Requisito | Estado |", "| --- | --- |"]
        for r in requirements:
            text = str(r.get("description") or "").replace("|", "/").replace("\n", " ")[:160]
            part = " (parcial)" if r.get("partial") else ""
            lines.append(f"| {r.get('id')}: {text} | {r.get('label') or r.get('status')}{part} |")
        reqs = "### Requisitos\n\n" + "\n".join(lines) + "\n\n"
    return (
        f"## Não concluído\n\n{objective.strip()}\n\n"
        f"O trabalho parou antes de cumprir todos os requisitos ({reason}). "
        "O que já foi feito continua salvo.\n\n"
        f"{reqs}### Pendências\n\n{table}\n\n"
        "### Para continuar\n\n"
        "- Resolva o motivo indicado (configuração, permissão, informação que faltou) "
        "e peça para continuar; as etapas concluídas não serão refeitas."
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
    """Diz se um texto tem a forma de um Markdown útil para o usuário.

    Args:
        text: texto candidato a resposta.

    Returns:
        Verdadeiro quando o texto é longo o bastante, não é JSON e tem marcas de Markdown.

    Observações:
        Um JSON de ferramenta não é resposta: tem a forma certa, mas não é texto para o usuário.
    """
    body = text.strip()
    if len(body) < 40:
        return False
    if body.startswith("{") or body.startswith("["):
        return False
    markers = ("#", "\n- ", "\n* ", "| --- |", "|---|", "```")
    return any(marker in body or body.startswith(marker.strip()) for marker in markers)


def extract_sources(*chunks: str) -> list[str]:
    """Recolhe os caminhos de arquivo citados nos trechos informados.

    Args:
        chunks: textos onde procurar os caminhos.

    Returns:
        Até doze caminhos distintos, ignorando os prefixos de diff `a/` e `b/`.
    """
    found: list[str] = []
    for chunk in chunks:
        for match in _PATH.findall(chunk or ""):
            if match.startswith(("a/", "b/")) or match in found:
                continue
            found.append(match)
    return found[:12]


def verification_footer(session, root) -> str:
    """Fatos verificados do trabalho, em texto determinístico.

    A resposta que o modelo escreve é curta e, por desenho, não cita verificações. Mas o
    usuário não pode depender do texto do modelo para saber se os testes passaram: uma
    resposta que afirma sucesso enquanto a suíte reprova é uma conclusão falsa. Este rodapé
    lista o que foi verificado, sem depender de julgamento do modelo.
    """
    from sqlalchemy import select

    from agent.orchestrator.consolidation import collect_evidences
    from agent.persistence.models import TaskModel

    tasks = list(session.scalars(select(TaskModel)).all())
    ids = {root.id}
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t.parent_id in ids and t.id not in ids:
                ids.add(t.id)
                changed = True

    passed: list[str] = []
    failed: list[str] = []
    inconclusive: list[str] = []
    for task in tasks:
        if task.id not in ids:
            continue
        for ev in collect_evidences(session, task.id):
            verifier = str(ev.get("verifier") or "verificação")
            summary = str(ev.get("summary") or "").strip()
            detail = ev.get("detail") or {}
            if detail.get("state") == "desatualizado":
                failed.append(f"`{verifier}`: evidência desatualizada (os arquivos mudaram depois)")
            elif ev.get("passed") is True:
                passed.append(f"`{verifier}`: {summary}" if summary else f"`{verifier}`: passou")
            elif ev.get("passed") is False:
                failed.append(f"`{verifier}`: {summary}" if summary else f"`{verifier}`: reprovou")
            else:
                inconclusive.append(f"`{verifier}`: inconclusivo")
        result = task.consolidated_result_json or {}
        tool_out = result.get("result")
        if isinstance(tool_out, dict) and tool_out.get("success") is False and tool_out.get("exit_code") is not None:
            lines = [line for line in str(tool_out.get("stdout") or tool_out.get("stderr") or "").splitlines() if line.strip()]
            tail = lines[-1][:160] if lines else f"código de saída {tool_out.get('exit_code')}"
            failed.append(f"«{task.title}» reprovou: {tail}")
    if not passed and not failed and not inconclusive:
        return ""
    parts = ["**Verificações executadas**"]
    parts.extend(f"- passou — {item}" for item in passed)
    parts.extend(f"- reprovou — {item}" for item in failed)
    parts.extend(f"- inconclusivo — {item}" for item in inconclusive)
    return "\n".join(parts)
