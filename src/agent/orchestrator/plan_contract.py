"""
Arquivo: src/agent/orchestrator/plan_contract.py
Nome: plan_contract.py
Propósito: normalização tolerante do plano que o modelo devolve.
Responsabilidade: camada de aplicação.
Componentes: normalize_kind, is_final_answer_label, normalize_depends, normalize_covers, normalize_plan_payload.
Dependências: agent.domain.enums, __future__, typing.
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.

Contrato tolerante do plano.

Um modelo pequeno rotula as etapas do jeito que entende: `kind: "final_answer"` para a resposta
final, `depends_on_indices` apontando para o índice errado, `metadata.verification` com um tipo que
não existe. Descartar o plano inteiro por causa de um rótulo é **perder o trabalho do modelo** — e
a validação do plano (`plan_validation.py`), que sabe reparar dependências, ferramentas e
requisitos, existe justamente para isso.

Aqui o plano é normalizado e cada desvio fica registrado como aviso: o plano continua utilizável e
a diagnóstico deixa de ser silenciosa. Nenhum campo isolado invalida o plano inteiro.
"""
from __future__ import annotations

from typing import Any

from agent.domain.enums import TaskKind

# Rótulos que o modelo usa para a etapa de resposta final. Todos viram `operation` com
# `metadata.final_answer`, que é como o orquestrador reconhece a etapa.
FINAL_ANSWER_LABELS = {
    "final_answer",
    "final-answer",
    "finalanswer",
    "resposta_final",
    "resposta final",
    "resposta",
    "answer",
    "conclusion",
    "conclusao",
    "conclusão",
    "summary",
    "resumo",
}

_KIND_ALIASES: dict[str, TaskKind] = {
    "objective": TaskKind.OBJECTIVE,
    "objetivo": TaskKind.OBJECTIVE,
    "goal": TaskKind.OBJECTIVE,
    "meta": TaskKind.OBJECTIVE,
    "subsystem": TaskKind.SUBSYSTEM,
    "subsistema": TaskKind.SUBSYSTEM,
    "component": TaskKind.SUBSYSTEM,
    "componente": TaskKind.SUBSYSTEM,
    "module": TaskKind.SUBSYSTEM,
    "modulo": TaskKind.SUBSYSTEM,
    "módulo": TaskKind.SUBSYSTEM,
    "operation": TaskKind.OPERATION,
    "operacao": TaskKind.OPERATION,
    "operação": TaskKind.OPERATION,
    "step": TaskKind.OPERATION,
    "etapa": TaskKind.OPERATION,
    "task": TaskKind.OPERATION,
    "tarefa": TaskKind.OPERATION,
    "action": TaskKind.OPERATION,
    "acao": TaskKind.OPERATION,
    "tool": TaskKind.OPERATION,
    "ferramenta": TaskKind.OPERATION,
    "default": TaskKind.OPERATION,
    "": TaskKind.OPERATION,
}


def normalize_kind(raw: Any) -> tuple[TaskKind, str | None]:
    """`kind` do modelo → `TaskKind`. Rótulo desconhecido vira `operation` com aviso, nunca erro."""
    text = str(raw or "").strip().lower()
    if text in FINAL_ANSWER_LABELS:
        # Rótulo conhecido: a etapa é a resposta final (o metadado é que a identifica).
        return TaskKind.OPERATION, None
    if text in _KIND_ALIASES:
        return _KIND_ALIASES[text], None
    return TaskKind.OPERATION, f"kind desconhecido '{raw}' tratado como 'operation'"


def is_final_answer_label(raw: Any) -> bool:
    """Diz se um rótulo de `kind` indica a etapa de resposta final.

    Args:
        raw: rótulo informado pelo modelo, de qualquer tipo.

    Returns:
        Verdadeiro quando o rótulo é um dos nomes reconhecidos de resposta final.
    """
    return str(raw or "").strip().lower() in FINAL_ANSWER_LABELS


def normalize_depends(raw: Any) -> tuple[list[int], list[str]]:
    """`depends_on_indices` → índices inteiros válidos. Índice inválido é descartado com aviso:
    dependência quebrada impede a criação da subtarefa, mas não invalida o plano."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["depends_on_indices não é uma lista; dependências ignoradas"]
    out: list[int] = []
    warnings: list[str] = []
    for item in raw:
        if isinstance(item, bool):
            warnings.append(f"depends_on_indices com valor booleano {item!r} ignorado")
            continue
        if isinstance(item, int):
            out.append(item)
            continue
        if isinstance(item, str) and item.strip().lstrip("-").isdigit():
            out.append(int(item.strip()))
            continue
        warnings.append(f"depends_on_indices com valor inválido {item!r} ignorado")
    return out, warnings


def normalize_covers(raw: Any) -> list[dict[str, Any]] | None:
    """`metadata.covers` → lista uniforme. `None` quando não declarado (a cobertura é herdada)."""
    if raw is None:
        return None
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append({"req": item.strip(), "partial": False, "part": ""})
        elif isinstance(item, dict) and item.get("req"):
            out.append(
                {
                    "req": str(item["req"]),
                    "partial": bool(item.get("partial")),
                    "part": str(item.get("part") or ""),
                }
            )
    return out


def normalize_plan_payload(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Payload cru do modelo → payload no formato de `DecompositionResult`, com avisos.

    A devolveção é sempre utilizável: campo inválido é corrigido ou descartado, nunca derruba o
    plano. Só um payload sem subtarefas é devolvido vazio (aí o chamador decide o fallback).
    """
    warnings: list[str] = []
    raw_tasks = data.get("subtasks")
    if not isinstance(raw_tasks, list):
        raw_tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    if not raw_tasks:
        return {"subtasks": []}, ["o modelo não devolveu nenhuma subtarefa"]

    subtasks: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            warnings.append(f"subtarefa {position} não é um objeto; ignorada")
            continue
        title = str(raw.get("title") or "").strip()
        objective = str(raw.get("objective") or raw.get("description") or "").strip()
        if not title and not objective:
            warnings.append(f"subtarefa {position} sem título nem objetivo; ignorada")
            continue
        if not title:
            title = objective[:80]
        if not objective:
            objective = title

        kind, kind_warning = normalize_kind(raw.get("kind"))
        if kind_warning:
            warnings.append(f"subtarefa {position}: {kind_warning}")

        metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
        if is_final_answer_label(raw.get("kind")):
            # O rótulo diz o que a etapa é; o orquestrador reconhece a etapa pelo metadado.
            metadata.setdefault("final_answer", True)
            metadata.setdefault("model_operation", True)

        depends, depends_warnings = normalize_depends(raw.get("depends_on_indices"))
        warnings.extend(f"subtarefa {position}: {item}" for item in depends_warnings)

        covers = normalize_covers(metadata.get("covers"))
        if covers is not None:
            metadata["covers"] = covers

        subtasks.append(
            {
                "title": title,
                "objective": objective,
                "kind": kind.value,
                "scope": raw.get("scope"),
                "acceptance_criteria": raw.get("acceptance_criteria"),
                "metadata": metadata or None,
                "depends_on_indices": depends,
            }
        )
    return {"subtasks": subtasks}, warnings
