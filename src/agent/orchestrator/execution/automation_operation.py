"""
Arquivo: src/agent/orchestrator/execution/automation_operation.py
Nome: automation_operation.py
Propósito: executar a etapa de automação — o modelo fala com as ferramentas de tarefas agendadas.
Responsabilidade: camada de aplicação — laço de ferramentas restrito às automações e resposta baseada no estado real.
Componentes: AutomationOperation (run, prompt, relatório).
Dependências: agent.orchestrator.tool_loop, agent.automation.intent, agent.tools.automations.
Observações: a resposta vem do estado devolvido pelas ferramentas; o modelo não afirma sucesso por conta própria.

A etapa em que o usuário conversa sobre tarefas agendadas.

O pedido da conversa ("todos os dias às 9h, verifique os testes") não é uma
alteração de arquivo: é uma pergunta sobre o **futuro**. Esta etapa dá ao modelo
exatamente as ferramentas de automação — e nada mais — para que ele não precise
escolher entre editar o disco e agendar um trabalho.

Duas garantias:

1. **A criação não ativa.** O modelo é instruído a mostrar a prévia e esperar a
   confirmação; o serviço devolve um token que só vale para a definição mostrada.
2. **A resposta é o estado real.** O texto entregue ao usuário é montado a partir do
   que a ferramenta devolveu (identificador, estado, próximo disparo), não do que o
   modelo disse que fez.
"""
from __future__ import annotations

from typing import Any

from agent.domain.enums import TaskStatus
from agent.domain.schemas import TaskStatusUpdate
from agent.observability import emit
from agent.orchestrator.tool_loop import ToolLoopOutcome, run_tool_loop
from agent.tools.automations import AUTOMATION_TOOL_CATALOG

PROMPT = """{now_line}
Fuso horário das automações: {timezone}
Projeto: {project}

{tool_catalog}

{context}

Pedido do usuário:
{objective}

Regras da etapa:
1. Para criar uma tarefa agendada, chame automation_create com name, objective e schedule
   (o horário em português, como o usuário falou: «todos os dias às 9h», «toda segunda-feira
   às 8h30», «amanhã às 14h», «a cada 4 horas»). Não escreva expressão cron.
2. A automação criada nasce DESABILITADA. Mostre a prévia (nome, objetivo, agenda, fuso,
   próximo disparo) e peça ao usuário que confirme. Só chame automation_enable depois que
   o usuário confirmar, repassando o confirmation_token devolvido pela criação.
3. Para consultar, alterar, suspender, executar ou remover: chame automation_list PRIMEIRO, para
   descobrir o identificador. Se o usuário disser «essa automação», «aquela» ou «a verificação
   diária», use o resultado da lista — jamais peça ao usuário um identificador que você mesmo
   consegue descobrir. Só pergunte quando houver mais de uma candidata; nesse caso, mostre as
   opções (id e nome) e peça a escolha.
4. Quando o pedido for uma ação (alterar, suspender, retomar, executar, remover), FAÇA a ação:
   consulte e, na mesma resposta, chame a ferramenta que a executa. Não pare na consulta.
5. Se faltar informação (o horário é vago, o nome é ambíguo, o objetivo não está claro), pergunte ao usuário.
6. Relate apenas o que as ferramentas devolveram.

Responda ao usuário em português, de forma curta, com o estado real da automação."""


class AutomationOperation:
    """Etapa de automação: o modelo opera as ferramentas de tarefas agendadas.

    Atributos:
        _executor: executor responsável pela etapa (dá a sessão, os serviços e as ferramentas).
    """

    def __init__(self, executor: Any) -> None:
        """Guarda o executor responsável pela etapa.

        Args:
            executor: executor da tarefa; fornece a sessão, os serviços e a finalização.
        """
        self._executor = executor

    @property
    def _runtime(self):
        """Colaboradores da execução (sessão, configurações, ferramentas)."""
        return self._executor.runtime

    def _context_block(self, project: Any, task: Any) -> str:
        """Contexto que o modelo precisa para resolver referências ("essa automação").

        O modelo recebe o estado persistido — as automações do projeto e as últimas
        mensagens da conversa — e não o histórico inteiro: um resumo estruturado
        basta para saber o que existe e o que o usuário está citando.

        Args:
            project: projeto da execução.
            task: etapa em curso.

        Returns:
            O bloco de contexto, pronto para o prompt.
        """
        lines: list[str] = []
        automations = self._existing_automations(project)
        if automations:
            lines.append("Automações existentes neste projeto:")
            lines.extend(automations)
        else:
            lines.append("Automações existentes neste projeto: nenhuma.")
        history = self._conversation_history(task)
        if history:
            lines.append("")
            lines.append("Mensagens anteriores desta conversa:")
            lines.extend(history)
        return "\n".join(lines) if lines else "Sem contexto anterior."

    def _existing_automations(self, project: Any) -> list[str]:
        """Resumo das automações do projeto, com identificador e estado.

        Args:
            project: projeto da execução.

        Returns:
            Uma linha por automação.
        """
        try:
            from agent.automation.chat_service import AutomationChatService

            service = AutomationChatService(
                self._runtime.session,
                self._runtime.settings,
                project_id=getattr(project, "id", None),
            )
            listed = service.list()
        except Exception:  # noqa: BLE001 — contexto é melhor-esforço
            return []
        lines: list[str] = []
        for item in listed.get("automations") or []:
            schedule = (item.get("schedule") or {}).get("summary")
            lines.append(
                f"- id={item.get('id')} | nome=«{item.get('name')}» | "
                f"estado={item.get('state')} | agenda={schedule} | "
                f"próximo={item.get('planned_next_run_at_local') or item.get('next_run_at_local')}"
            )
            token = item.get("confirmation_token")
            if token:
                lines.append(f"  confirmation_token: {token}")
        return lines
    def _conversation_history(self, task: Any, *, limit: int = 5) -> list[str]:
        """Últimas mensagens da conversa, para resolver «esta tarefa».

        Args:
            task: etapa em curso.
            limit: número máximo de mensagens.

        Returns:
            Uma linha por mensagem anterior.
        """
        conversation_id = getattr(task, "conversation_id", None)
        if not conversation_id:
            return []
        try:
            from sqlalchemy import select

            from agent.persistence.models import TaskModel

            rows = self._runtime.session.scalars(
                select(TaskModel)
                .where(TaskModel.conversation_id == conversation_id)
                .order_by(TaskModel.created_at.desc())
                .limit(limit + 1)
            ).all()
        except Exception:  # noqa: BLE001 — contexto é melhor-esforço
            return []
        lines: list[str] = []
        for row in rows:
            if str(row.id) == str(task.id):
                continue
            lines.append(f"- {row.objective}")
            if len(lines) >= limit:
                break
        return lines

    async def run(
        self,
        run: Any,
        project: Any,
        task: Any,
        config: dict,
        root_path: str,
        ctx: Any,
    ) -> dict[str, Any]:
        """Executa a etapa de automação e devolve o desfecho.

        Args:
            run: execução em curso.
            project: projeto da execução.
            task: etapa a executar.
            config: configuração do run.
            root_path: pasta de trabalho (não é alterada por esta etapa).
            ctx: contexto das ferramentas.

        Returns:
            Dicionário com `action` e o resultado da etapa.
        """
        from agent.orchestrator.closing import local_now_line
        from agent.orchestrator.execution.providers import (
            profile_from_config,
            select_provider,
            supports_tool_loop,
        )
        from agent.providers.base import ChatCompletionRequest, ChatMessage
        from agent.providers.observed import observed_chat

        session = self._runtime.session
        settings = self._runtime.settings
        tools = self._runtime.tools
        objective = task.objective or ""
        timezone = str(getattr(settings, "automation_timezone", "") or "America/Sao_Paulo")

        factory = self._runtime.provider_factory or select_provider
        provider = factory(settings, config)
        profile = profile_from_config(config, settings, provider)
        prompt = PROMPT.format(
            now_line=local_now_line(),
            timezone=timezone,
            project=str(getattr(project, "name", "") or getattr(project, "id", "")),
            tool_catalog=AUTOMATION_TOOL_CATALOG,
            context=self._context_block(project, task),
            objective=objective[:2000],
        )
        self._executor.note_thought(
            run, task, "Conferindo as tarefas agendadas com as ferramentas de automação.", phase="tool"
        )

        results: list[dict[str, Any]] = []

        async def _on_tool_call(entry: dict[str, Any], result: dict[str, Any]) -> None:
            """Guarda o resultado real de cada chamada de ferramenta."""
            results.append(result)
            emit(
                "automation.chat_tool",
                {
                    "tool": entry.get("tool"),
                    "success": bool(result.get("success")),
                    "summary": entry.get("summary"),
                },
                task_id=task.id,
            )

        if supports_tool_loop(provider):
            outcome = await run_tool_loop(
                provider=provider,
                messages=[ChatMessage(role="user", content=prompt)],
                profile=profile,
                registry=tools,
                ctx=ctx,
                approved=True,
                tool_ids=list(_automation_tool_ids()),
                max_iterations=max(1, int(settings.max_tool_iterations)),
                max_tool_calls=max(1, int(settings.max_tool_calls)),
                stream=config.get("stream", True) is not False,
                on_tool_call=_on_tool_call,
                final_tools=list(_automation_tool_ids()),
                final_tools_after=(),
                final_instruction=(
                    "Você já fez a operação. Responda agora ao usuário com o estado real "
                    "devolvido pela ferramenta. Não peça mais ferramentas."
                ),
                purpose="automation",
            )
        else:
            resp = await observed_chat(
                provider,
                ChatCompletionRequest(
                    messages=[ChatMessage(role="user", content=prompt)],
                    profile=profile,
                ),
                purpose="automation",
                stream=config.get("stream", True) is not False,
            )
            outcome = ToolLoopOutcome(content=resp.content or "", iterations=1, stop_reason="final")

        markdown = _compose(outcome, results)
        emit(
            "automation.chat_result",
            {
                "action": "automation_operation",
                "tools": [str(item.get("tool")) for item in (outcome.tool_log or [])],
                "chars": len(markdown),
            },
            task_id=task.id,
        )
        task.consolidated_result_json = {
            "final_answer": True,
            "markdown": markdown,
            "automation_operation": True,
            "tools": [str(item.get("tool")) for item in (outcome.tool_log or [])],
            "sources": [],
        }
        self._executor.note_thought(run, task, markdown[:280], phase="tool")
        self._runtime.tasks.update_status(task.id, TaskStatusUpdate(status=TaskStatus.VERIFYING))
        done = await self._executor.finalize_verification(run, project, task, root_path)
        done["thought"] = markdown[:280]
        session.flush()
        return done


def _automation_tool_ids() -> tuple[str, ...]:
    """Identificadores das ferramentas de automação.

    Returns:
        A lista de ids oferecidas ao modelo nesta etapa.
    """
    from agent.orchestrator.tool_loop import AUTOMATION_TOOLS

    return AUTOMATION_TOOLS


def _compose(outcome: ToolLoopOutcome, results: list[dict[str, Any]]) -> str:
    """Monta o texto entregue ao usuário a partir do estado real.

    Args:
        outcome: desfecho do laço de ferramentas.
        results: resultados completos das chamadas de ferramenta.

    Returns:
        O texto final, em Markdown.
    """
    from agent.tools.automations import (
        render_result,  # renderer compartilhado com as ferramentas
    )

    if results:
        last = results[-1]
        rendered = render_result(last)
        if rendered.strip():
            return rendered
        text = (outcome.content or "").strip()
        return text or "A operação não devolveu detalhe."
    text = (outcome.content or "").strip()
    if text:
        return text
    return (
        "Não consegui executar a operação de automação. "
        "Verifique se o runtime de automações está disponível."
    )


__all__ = ["AutomationOperation"]
