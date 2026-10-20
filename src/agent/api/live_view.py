"""
Arquivo: src/agent/api/live_view.py
Nome: live_view.py
Propósito: montar a linha do tempo de pensamentos e o texto legível das ações do orquestrador.
Responsabilidade: camada de apresentação — visão ao vivo; não decide nem executa nada.
Componentes: thought_trace, mark_repeated_thought, how_for_task, ACTION_COPY.
Dependências: agent.persistence.models (EventLogModel), agent.i18n.locale (tradução).
Observações: a frase repetida é marcada, e não escondida — a interface precisa ver que não houve diferença.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.i18n.locale import translate
from agent.persistence.models import EventLogModel
from agent.services.conversation_service import locale_for_task


def thought_trace(session: Session, project_id: uuid.UUID, tasks: list) -> list[dict]:
    """Monta a linha do tempo legível dos pensamentos e das ações do orquestrador.

    Args:
        session: sessão do banco da requisição.
        project_id: projeto cujos eventos são lidos.
        tasks: tarefas do projeto, usadas para título e idioma.

    Returns:
        Até dezesseis eventos em ordem cronológica, com a fase, o texto traduzido e a contagem de repetição.

    Observações:
        Ações internas sem texto legível para o usuário são omitidas; a frase repetida é marcada, não escondida.
    """
    by_id = {task.id: task for task in tasks}
    titles = {task.id: task.title for task in tasks}
    stmt = (
        select(EventLogModel)
        .where(
            EventLogModel.project_id == project_id,
            EventLogModel.event_type.in_(("agent.thought", "orchestrator.action")),
        )
        .order_by(EventLogModel.created_at.desc())
        .limit(24)
    )
    rows = list(session.scalars(stmt).all())
    rows.reverse()
    thoughts: list[dict] = []
    for event in rows:
        payload = event.payload_json or {}
        task_title = titles.get(event.task_id)
        if event.event_type == "agent.thought":
            text = str(payload.get("text") or "")
            phase = payload.get("phase") or "thinking"
        else:
            custom = payload.get("thought")
            if custom:
                text = str(custom)[:280]
                phase = "model"
            else:
                action = payload.get("action") or "passo"
                if action in {
                    "operation_ready",
                    "promoted_ready",
                    "planning_wait_children",
                    "started_planning",
                    "operation_wait_deps",
                    "retry_ready",
                    "skipped_to_verify",
                    "completed_without_verification",
                    "waiting",
                    "run_terminal",
                }:
                    continue
                text = ACTION_COPY.get(action, (action, ""))[0]
                if task_title and action != "run_completed":
                    text = f"{text} — {task_title}"
                phase = "step"
        text = text.strip()
        locale = locale_for_task(session, by_id.get(event.task_id))
        if " — " in text:
            head, tail = text.split(" — ", 1)
            text = f"{translate(head, locale)} — {translate(tail, locale)}"
        else:
            text = translate(text, locale)
        if not text:
            continue
        item = {
            "phase": phase,
            "text": text,
            "task": translate(task_title, locale) if task_title else None,
            "task_id": str(event.task_id) if event.task_id else None,
            "at": event.created_at.isoformat() if event.created_at else None,
        }
        mark_repeated_thought(thoughts, item)
    return thoughts[-16:]


def mark_repeated_thought(thoughts: list[dict], item: dict) -> None:
    """A mesma frase de novo fica marcada, para a interface mostrar que não houve diferença."""
    text = item["text"]
    if thoughts and thoughts[-1]["text"] == text:
        thoughts[-1]["repeat"] = int(thoughts[-1].get("repeat") or 1) + 1
        return
    item["repeat"] = 2 if any(prev["text"] == text for prev in thoughts) else 1
    thoughts.append(item)


def how_for_task(task) -> str:
    """Descreve em uma frase como a tarefa será executada.

    Args:
        task: tarefa com os metadados da operação.

    Returns:
        Uma frase legível indicando ferramenta, verificação, operação do modelo ou chamada MCP.

    Observações:
        Sem metadados, explica que a escolha do passo vem da máquina de estados do orquestrador.
    """
    meta = task.metadata_json or {}
    if meta.get("tool"):
        return f"Ferramenta `{meta['tool']}` com argumentos locais."
    if meta.get("verification"):
        spec = meta["verification"]
        return f"Verificação determinística ({spec.get('type', 'check')})."
    if meta.get("model_operation"):
        return "O modelo local propõe a alteração; o runtime grava o arquivo e verifica."
    if meta.get("mcp_tool"):
        return f"Chamada MCP `{meta['mcp_tool']}`."
    return "O orquestrador escolhe o próximo passo pela máquina de estados, sem depender só do modelo."


ACTION_COPY = {
    "started_planning": ("Planejando", "O orquestrador abriu o objetivo e registrou a memória canônica."),
    "decomposed": ("Dividindo o trabalho", "A tarefa foi quebrada em subtarefas menores e verificáveis."),
    "replanned": ("Replanejou", "Uma etapa parou. O que já foi feito permanece e o restante do plano foi refeito."),
    "operation_ready": ("Pronta para executar", "Dependências ok. A operação pode rodar a ferramenta ou o modelo."),
    "planning_wait_children": ("Aguardando subtarefas", "O pai espera os filhos terminarem antes de consolidar."),
    "promoted_ready": ("Liberada", "Dependências satisfeitas; a tarefa passou para pronta."),
    "retry_ready": ("Nova tentativa", "A falha anterior foi recuperável. Vai tentar de novo."),
    "model_operation_invalid": ("Resposta inválida", "O modelo não devolveu o JSON esperado. Vai repetir."),
    "model_operation_failed": ("Escrita falhou", "A alteração proposta não foi gravada."),
    "tool_executed": ("Ferramenta", "A ferramenta rodou e o resultado foi registrado."),
    "verified_ok": ("Verificado", "O teste ou a checagem passou e gerou evidência."),
    "verify_failed": ("Verificação falhou", "O critério não passou. A tarefa volta para nova tentativa."),
    "verify_inconclusive": ("Verificação inconclusiva", "Não deu para decidir. A tarefa foi bloqueada."),
    "completed_without_verification": ("Concluída sem teste", "Não havia critério determinístico nesta operação."),
    "consolidated_parent": ("Consolidando", "Os resultados dos filhos sobem para a tarefa pai."),
    "blocked_contract": ("Bloqueada", "Falta um contrato obrigatório antes de continuar."),
    "blocked_loop": ("Loop detectado", "A mesma saída se repetiu. A execução parou para não girar à toa."),
    "blocked_attempts": ("Limite de tentativas", "Esgotou o orçamento de tentativas desta tarefa."),
    "blocked_decompose": ("Sem plano", "Não foi possível decompor o objetivo."),
    "blocked_no_metadata": ("Sem instrução", "A operação não diz qual ferramenta ou verificação usar."),
    "global_verify_reopen": ("Reabrindo", "A checagem global achou evidência faltando e reabriu tarefas."),
    "global_verify_failed": ("Objetivo incompleto", "Os critérios globais não foram atendidos."),
    "final_answer": ("Resposta final", "A conclusão foi escrita para o usuário."),
    "run_completed": ("Concluído", "O objetivo e as evidências foram aceitos."),
    "run_terminal": ("Encerrado", "Este run já estava finalizado."),
    "waiting": ("Aguardando", "Não há tarefa pronta neste instante."),
    "mcp_tool": ("MCP", "Uma ferramenta MCP local foi chamada."),
    "skipped_to_verify": ("Indo verificar", "A operação foi encaminhada para verificação."),
}
