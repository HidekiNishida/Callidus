"""
Arquivo: src/agent/automation/chat_service.py
Nome: chat_service.py
Propósito: aplicar, pelo chat, as operações do subsistema de automações.
Responsabilidade: camada de aplicação — serviço único que o chat usa para criar, consultar e gerenciar automações.
Componentes: AutomationChatService, AutomationChatError.
Dependências: agent.automation.store, agent.automation.dispatcher, agent.automation.executor, agent.automation.dependencies, agent.automation.natural, agent.automation.timezones.
Observações: o serviço reutiliza o runtime existente; não há HTTP, tabelas paralelas nem segunda fonte de verdade.

O serviço que o chat usa para falar com as automações.

O modelo **não** chama a API HTTP do próprio Callidus: ele chama este serviço,
que por sua vez usa os mesmos componentes do runtime — `AutomationService` para a
definição, `Dispatcher` para o disparo idempotente, `AutomationExecutor` para a
execução e `DependencyResolver` para a prontidão. Assim há uma única fonte de
verdade (o SQLite) e um único caminho de execução.

Três decisões que o serviço garante:

1. **A criação não ativa.** A automação nasce desabilitada e devolve um *token de
   confirmação* ligado à definição apresentada. Ativar exige esse token: se o
   horário, a ação ou as permissões mudarem depois da prévia, o token muda e a
   confirmação precisa ser refeita.
2. **Nada é inventado.** O texto do usuário vira gatilho pelo interpretador
   temporal; texto ambíguo vira pergunta, não horário escolhido.
3. **O estado relatado é o estado real.** O resumo devolvido vem do registro
   persistido, não do que o modelo disse.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from agent.automation.contracts import (
    AutomationDefinition,
    CallidusAction,
    DependencySpec,
    PermissionSpec,
    ScriptAction,
    TriggerSpec,
)
from agent.automation.dependencies import DependencyResolver
from agent.automation.dispatcher import Dispatcher
from agent.automation.enums import (
    AutomationState,
    FiringState,
    ObjectiveMode,
    TargetKind,
    TriggerKind,
)
from agent.automation.executor import AutomationExecutor
from agent.automation.natural import DEFAULT_TIMEZONE, describe_trigger, parse_schedule
from agent.automation.store import AutomationNotFound, AutomationService
from agent.automation.timezones import resolve_timezone
from agent.config import Settings, get_settings
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    ProjectModel,
    ProjectRemoteModel,
)

# Campos que definem a identidade material da automação: mudá-los invalida a
# confirmação já concedida.
_TOKEN_FIELDS = (
    "name",
    "description",
    "trigger_json",
    "action_json",
    "dependencies_json",
    "permissions_json",
    "policy_json",
    "timezone",
    "missed_policy",
    "objective_mode",
    "objective_json",
)


class AutomationChatError(RuntimeError):
    """Falha de negócio na operação de automação pedida pelo chat.

    Atributos:
        payload: detalhe serializável do erro (pergunta, candidatos, campos).
    """

    def __init__(self, message: str, **payload: Any) -> None:
        """Cria o erro com o detalhe da falha.

        Args:
            message: mensagem legível.
            payload: campos extras devolvidos ao modelo.
        """
        super().__init__(message)
        self.message = message
        self.payload = payload


class AutomationChatService:
    """Operações de automação disponíveis ao chat.

    Atributos:
        _session: sessão do banco (a mesma da execução em curso).
        _settings: configurações do processo.
        _project_id: projeto da conversa, quando conhecido.
        _conversation_id: conversa que pediu a operação, quando conhecida.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        project_id: uuid.UUID | str | None = None,
        conversation_id: uuid.UUID | str | None = None,
    ) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
            settings: configurações do processo; quando ausentes, são lidas do ambiente.
            project_id: projeto ao qual as automações pertencem.
            conversation_id: conversa que pediu a operação.
        """
        self._session = session
        self._settings = settings or get_settings()
        self._project_id = _uuid_or_none(project_id)
        self._conversation_id = _uuid_or_none(conversation_id)
        self._automations = AutomationService(session)

    # ------------------------------------------------------------- criação

    async def create(
        self,
        *,
        name: str,
        objective: str,
        schedule: str | None = None,
        cron: str | None = None,
        run_at: str | None = None,
        interval_seconds: int | None = None,
        action_kind: str = "callidus",
        command: list[str] | None = None,
        script: str | None = None,
        timezone: str | None = None,
        description: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        allow_scripts: bool = False,
        allowed_commands: list[str] | None = None,
        allowed_paths: list[str] | None = None,
        conversation_id: str | None = None,
        objective_mode: str = ObjectiveMode.FROZEN.value,
        model_id: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma automação **desabilitada**, com a definição validada.

        Args:
            name: nome da automação.
            objective: o que a automação faz (ação Callidus) ou a descrição do script.
            schedule: horário em linguagem natural ("todos os dias às 9h").
            cron: expressão cron, quando o usuário pediu uma recorrência exata.
            run_at: instante único (ISO 8601), para execução única.
            interval_seconds: intervalo fixo, para recorrência por intervalo.
            action_kind: `callidus` (trabalho do agente) ou `script` (determinístico).
            command: argv do script, quando a ação é de script.
            script: caminho do script, quando a ação é de script.
            timezone: fuso do usuário; quando ausente, usa o configurado.
            description: descrição livre da automação.
            dependencies: dependências a verificar antes do disparo.
            allow_scripts: autoriza a execução de scripts.
            allowed_commands: executáveis autorizados.
            allowed_paths: pastas autorizadas.
            conversation_id: conversa a associar.
            objective_mode: `frozen` (padrão) ou `latest`.
            model_id: modelo a usar na execução.
            provider: provedor a usar na execução.

        Returns:
            O resumo da automação criada, com a prévia e o token de confirmação.

        Raises:
            AutomationChatError: quando o pedido é incompleto, ambíguo ou inválido.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            raise AutomationChatError("informe o nome da automação", field="name")
        tz = self._resolve_timezone(timezone)
        link = self._existing_conversation(conversation_id)
        trigger = self._build_trigger(
            schedule=schedule,
            cron=cron,
            run_at=run_at,
            interval_seconds=interval_seconds,
            timezone=tz,
        )
        action, permissions = self._build_action(
            action_kind=action_kind,
            objective=objective,
            command=command,
            script=script,
            conversation_id=link,
            objective_mode=objective_mode,
            model_id=model_id,
            provider=provider,
            allow_scripts=allow_scripts,
            allowed_commands=allowed_commands,
            allowed_paths=allowed_paths,
        )
        specs = self._build_dependencies(dependencies)
        if self._project_id is None:
            raise AutomationChatError(
                "não sei a qual projeto esta automação pertence",
                field="project_id",
            )
        definition = AutomationDefinition(
            name=clean_name,
            description=description,
            project_id=str(self._project_id),
            trigger=trigger,
            action=action,
            dependencies=specs,
            permissions=permissions,
            timezone=tz,
            conversation_id=link,
            objective_mode=ObjectiveMode(objective_mode),
            state=AutomationState.DISABLED.value,
        )
        duplicate = self._find_duplicate(definition)
        if duplicate is not None:
            summary = self._summarize(duplicate)
            summary["duplicate"] = True
            return {
                "success": True,
                "automation": summary,
                "message": (
                    "Já existe uma automação igual nesta conversa; nada foi criado de novo."
                ),
            }
        row = self._automations.create(definition)
        self._session.flush()
        summary = self._summarize(row)
        return {
            "success": True,
            "automation": summary,
            "readiness": await self._readiness(row),
            "runtime": self.runtime_status(),
            "needs_confirmation": True,
            "message": (
                "Automação criada e **desabilitada**. Mostre a prévia ao usuário e peça "
                "confirmação antes de ativar."
            ),
        }

    def _build_trigger(
        self,
        *,
        schedule: str | None,
        cron: str | None,
        run_at: str | None,
        interval_seconds: int | None,
        timezone: str,
    ) -> TriggerSpec:
        """Monta o gatilho a partir do que o usuário pediu.

        Args:
            schedule: texto em linguagem natural.
            cron: expressão cron.
            run_at: instante único.
            interval_seconds: intervalo fixo.
            timezone: fuso da automação.

        Returns:
            O gatilho validado.

        Raises:
            AutomationChatError: quando falta o horário ou o texto é ambíguo.
        """
        if cron and cron.strip():
            spec = TriggerSpec(kind=TriggerKind.CRON, cron=cron.strip(), timezone=timezone)
        elif run_at and str(run_at).strip():
            moment = _parse_instant(str(run_at), timezone)
            spec = TriggerSpec(kind=TriggerKind.ONCE, run_at=moment, timezone=timezone)
        elif interval_seconds and int(interval_seconds) > 0:
            spec = TriggerSpec(
                kind=TriggerKind.INTERVAL,
                interval_seconds=int(interval_seconds),
                run_at=datetime.now(timezone.utc),
                timezone=timezone,
            )
        elif schedule and schedule.strip():
            intent = parse_schedule(schedule, timezone=timezone)
            if not intent.resolved:
                raise AutomationChatError(
                    intent.question or "não consegui entender o horário pedido",
                    question=intent.question,
                    field="schedule",
                    understood=intent.kind,
                )
            spec = intent.trigger
        else:
            raise AutomationChatError(
                "informe o horário da automação (por exemplo «amanhã às 14h» ou «todos os dias às 9h»)",
                field="schedule",
            )
        self._validate_trigger(spec)
        return spec

    def _validate_trigger(self, spec: TriggerSpec) -> None:
        """Confere que o gatilho é executável pelo runtime.

        Args:
            spec: gatilho a validar.

        Raises:
            AutomationChatError: quando o gatilho não é válido.
        """
        from agent.automation.triggers import build_trigger

        try:
            build_trigger(spec)
        except Exception as exc:  # erro de contrato vira recusa clara
            raise AutomationChatError(
                f"o horário pedido não é válido: {exc}", field="schedule"
            ) from exc

    def _build_action(
        self,
        *,
        action_kind: str,
        objective: str,
        command: list[str] | None,
        script: str | None,
        conversation_id: str | None,
        objective_mode: str,
        model_id: str | None,
        provider: str | None,
        allow_scripts: bool,
        allowed_commands: list[str] | None,
        allowed_paths: list[str] | None,
    ) -> tuple[Any, PermissionSpec]:
        """Monta a ação e as permissões da automação.

        Args:
            action_kind: `callidus` ou `script`.
            objective: objetivo da automação.
            command: argv do script.
            script: caminho do script.
            conversation_id: conversa a associar.
            objective_mode: `frozen` ou `latest`.
            model_id: modelo da execução.
            provider: provedor da execução.
            allow_scripts: autoriza a execução de scripts.
            allowed_commands: executáveis autorizados.
            allowed_paths: pastas autorizadas.

        Returns:
            Tupla com a ação e as permissões.

        Raises:
            AutomationChatError: quando a ação é inválida ou pede permissão demais.
        """
        kind = (action_kind or "callidus").strip().lower()
        if kind == "callidus":
            action = CallidusAction(
                objective=(objective or "").strip() or None,
                conversation_id=str(conversation_id or self._conversation_id or "") or None,
                objective_mode=ObjectiveMode(objective_mode),
                model_id=model_id,
                provider=provider,
            )
            if not action.objective:
                raise AutomationChatError(
                    "informe o que a automação deve fazer (o objetivo)", field="objective"
                )
            permissions = PermissionSpec(
                allow_scripts=False,
                allowed_commands=list(allowed_commands or []),
                allowed_paths=list(allowed_paths or []),
                approved_resources=[],
            )
            return action, permissions
        if kind == "script":
            argv = [str(item) for item in (command or []) if str(item).strip()]
            if not argv and not script:
                raise AutomationChatError(
                    "informe o comando do script (ou o caminho do script)", field="command"
                )
            if not allow_scripts:
                raise AutomationChatError(
                    "executar scripts exige autorização explícita: peça ao usuário para "
                    "autorizar e chame de novo com allow_scripts=true e o executável em "
                    "allowed_commands",
                    field="allow_scripts",
                    requires_permission=True,
                )
            executable = argv[0] if argv else str(script)
            allowed = [str(item) for item in (allowed_commands or []) if str(item).strip()]
            if not allowed:
                allowed = [executable]
            if executable not in allowed:
                raise AutomationChatError(
                    f"o executável «{executable}» não está na lista de comandos autorizados",
                    field="allowed_commands",
                )
            action = ScriptAction(
                command=argv,
                script=str(script) if script else None,
                success_exit_codes=[0],
            )
            permissions = PermissionSpec(
                allow_scripts=True,
                allowed_commands=allowed,
                allowed_paths=list(allowed_paths or []),
                approved_resources=[executable],
            )
            return action, permissions
        raise AutomationChatError(
            f"tipo de ação desconhecido: {action_kind} (use «callidus» ou «script»)",
            field="action_kind",
        )

    def _build_dependencies(
        self, dependencies: list[dict[str, Any]] | None
    ) -> list[DependencySpec]:
        """Valida as dependências pedidas.

        Args:
            dependencies: dependências informadas.

        Returns:
            A lista de dependências validadas.

        Raises:
            AutomationChatError: quando uma dependência é malformada.
        """
        specs: list[DependencySpec] = []
        for item in dependencies or []:
            try:
                specs.append(DependencySpec.model_validate(item))
            except Exception as exc:
                raise AutomationChatError(
                    f"dependência inválida: {exc}", field="dependencies"
                ) from exc
        return specs

    def _existing_conversation(self, conversation_id: str | None) -> str | None:
        """Conversa a associar, quando ela realmente existe no banco.

        Args:
            conversation_id: conversa informada.

        Returns:
            O identificador da conversa, ou `None` quando não há conversa válida.
        """
        from agent.persistence.models import ConversationModel

        candidate = conversation_id or (str(self._conversation_id) if self._conversation_id else None)
        if not candidate:
            return None
        if self._session.get(ConversationModel, _uuid_or_none(candidate)) is None:
            return None
        return str(candidate)

    def _find_duplicate(self, definition: AutomationDefinition) -> AutomationModel | None:
        """Procura uma automação equivalente, para não duplicar registros.

        Args:
            definition: definição que seria criada.

        Returns:
            A automação equivalente, ou `None` quando não há.
        """
        wanted_trigger = definition.trigger.model_dump(mode="json")
        wanted_action = (
            definition.action.model_dump(mode="json")
            if hasattr(definition.action, "model_dump")
            else {}
        )
        for row in self._automations.list(self._project_id):
            if (row.trigger_json or {}) != wanted_trigger:
                continue
            if (row.action_json or {}) != wanted_action:
                continue
            if row.name.strip().casefold() != definition.name.strip().casefold():
                continue
            return row
        return None

    # --------------------------------------------------------- consultas

    def list(
        self,
        *,
        state: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Lista as automações visíveis para a conversa.

        Args:
            state: filtra por estado (`enabled`, `suspended`, `disabled`).
            query: filtra por nome (correspondência parcial, sem acento).
            limit: número máximo devolvido.

        Returns:
            Dicionário com a lista resumida e a contagem.
        """
        rows = self._automations.list(self._project_id, state=state)
        if query:
            needle = _normalize(query)
            rows = [row for row in rows if needle in _normalize(row.name)]
        rows = rows[: max(1, min(int(limit), 200))]
        return {
            "success": True,
            "count": len(rows),
            "automations": [self._summarize(row, brief=True) for row in rows],
        }

    def get(self, automation_id: str | None = None, *, query: str | None = None) -> dict[str, Any]:
        """Detalha uma automação, resolvendo o identificador ou o nome citado.

        Args:
            automation_id: identificador da automação.
            query: nome (ou parte dele) citado pelo usuário.

        Returns:
            O resumo da automação.

        Raises:
            AutomationChatError: quando não há correspondência, ou há mais de uma.
        """
        row = self._resolve(automation_id, query)
        return {
            "success": True,
            "automation": self._summarize(row),
            "firings": self._recent_firings(row.id, limit=10),
        }

    def _resolve(self, automation_id: str | None, query: str | None) -> AutomationModel:
        """Resolve a automação pedida pelo identificador ou pelo nome.

        Args:
            automation_id: identificador da automação.
            query: nome citado pelo usuário.

        Returns:
            A automação encontrada.

        Raises:
            AutomationChatError: quando não há correspondência, ou há mais de uma.
        """
        if automation_id:
            try:
                return self._automations.get(automation_id)
            except AutomationNotFound as exc:
                raise AutomationChatError(
                    f"não existe automação com o identificador {automation_id}",
                    field="automation_id",
                ) from exc
        if query:
            needle = _normalize(query)
            matches = [
                row
                for row in self._automations.list(self._project_id)
                if needle and needle in _normalize(row.name)
            ]
            if not matches:
                raise AutomationChatError(
                    f"nenhuma automação corresponde a «{query}»", field="query"
                )
            if len(matches) > 1:
                raise AutomationChatError(
                    "mais de uma automação corresponde ao nome citado",
                    field="query",
                    candidates=[
                        {"id": str(row.id), "name": row.name, "state": row.state}
                        for row in matches
                    ],
                )
            return matches[0]
        raise AutomationChatError(
            "informe o identificador ou o nome da automação", field="automation_id"
        )

    # --------------------------------------------------------- alterações

    def update(
        self,
        automation_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        objective: str | None = None,
        schedule: str | None = None,
        cron: str | None = None,
        run_at: str | None = None,
        interval_seconds: int | None = None,
        timezone: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        missed_policy: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Altera uma automação existente.

        Args:
            automation_id: identificador da automação.
            name: novo nome.
            description: nova descrição.
            objective: novo objetivo (ação Callidus).
            schedule: novo horário em linguagem natural.
            cron: nova expressão cron.
            run_at: novo instante único.
            interval_seconds: novo intervalo fixo.
            timezone: novo fuso.
            dependencies: novas dependências.
            missed_policy: nova política de disparos perdidos.
            confirm: o usuário confirmou a alteração material; sem isso, uma
                automação habilitada é suspensa até a confirmação.

        Returns:
            O resumo da automação alterada.

        Raises:
            AutomationChatError: quando a automação não existe ou o pedido é inválido.
        """
        row = self._resolve(automation_id, None)
        was_enabled = row.state == AutomationState.ENABLED.value
        changes: dict[str, Any] = {}
        material = False
        if name and name.strip():
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = description
        if timezone:
            changes["timezone"] = self._resolve_timezone(timezone)
            material = True
        if missed_policy:
            changes["missed_policy"] = missed_policy
        if dependencies is not None:
            changes["dependencies"] = [
                spec.model_dump(mode="json") for spec in self._build_dependencies(dependencies)
            ]
            material = True
        if schedule or cron or run_at or interval_seconds:
            tz = self._resolve_timezone(timezone or row.timezone)
            trigger = self._build_trigger(
                schedule=schedule,
                cron=cron,
                run_at=run_at,
                interval_seconds=interval_seconds,
                timezone=tz,
            )
            changes["trigger"] = trigger.model_dump(mode="json")
            changes["timezone"] = tz
            material = True
        if objective and objective.strip():
            action = dict(row.action_json or {})
            if action.get("kind") == "callidus":
                action["objective"] = objective.strip()
                changes["action"] = action
                # O objetivo congelado precisa acompanhar a nova ação.
                changes["freeze_objective"] = True
                material = True
            else:
                raise AutomationChatError(
                    "esta automação executa um script; o objetivo não se aplica",
                    field="objective",
                )
        if not changes:
            raise AutomationChatError("nada para alterar", field="changes")
        updated = self._automations.update(row.id, changes)
        self._session.flush()
        suspended = False
        if was_enabled and material and not confirm:
            # Mudança material sem confirmação: a automação para até o usuário confirmar
            # a nova definição. É o que impede que uma definição não aprovada rode.
            updated = self._automations.set_state(updated.id, AutomationState.SUSPENDED)
            self._session.flush()
            suspended = True
        return {
            "success": True,
            "automation": self._summarize(updated),
            "material_change": material,
            "suspended_pending_confirmation": suspended,
            "needs_confirmation": suspended or material,
            "message": (
                "Automação alterada e suspensa: a definição mudou, então a confirmação "
                "anterior não vale mais. Mostre a nova prévia e peça confirmação para "
                "reativar."
                if suspended
                else "Automação alterada. A definição mudou: mostre a nova prévia ao usuário."
            ),
        }

    def set_state(
        self,
        automation_id: str,
        state: str,
        *,
        confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        """Muda o estado da automação (ativar, suspender, desativar).

        Args:
            automation_id: identificador da automação.
            state: `enabled`, `suspended` ou `disabled`.
            confirmation_token: token da prévia apresentada ao usuário.

        Returns:
            O resumo da automação no novo estado.

        Raises:
            AutomationChatError: quando o estado é inválido ou a confirmação não vale.
        """
        row = self._resolve(automation_id, None)
        try:
            target = AutomationState(str(state).strip().lower())
        except ValueError as exc:
            raise AutomationChatError(
                f"estado desconhecido: {state} (use enabled, suspended ou disabled)",
                field="state",
            ) from exc
        if target is AutomationState.ENABLED:
            expected = self._confirmation_token(row)
            if not confirmation_token:
                raise AutomationChatError(
                    "ativar exige o token de confirmação da prévia apresentada ao usuário "
                    "(confirmation_token)",
                    field="confirmation_token",
                    requires_confirmation=True,
                )
            if str(confirmation_token).strip() != expected:
                raise AutomationChatError(
                    "a definição mudou depois da prévia: a confirmação anterior não vale. "
                    "Mostre a prévia atual e peça nova confirmação.",
                    field="confirmation_token",
                    requires_confirmation=True,
                    current_token=expected,
                )
        updated = self._automations.set_state(row.id, target)
        self._session.flush()
        return {
            "success": True,
            "automation": self._summarize(updated),
            "needs_confirmation": False,
            "message": {
                AutomationState.ENABLED: "Automação ativada.",
                AutomationState.SUSPENDED: "Automação suspensa: os disparos futuros ficam parados.",
                AutomationState.DISABLED: "Automação desativada.",
            }[target],
        }

    # ---------------------------------------------------------- execução

    async def run_now(self, automation_id: str, *, wait: bool = False) -> dict[str, Any]:
        """Executa a automação imediatamente, sem esperar o próximo horário.

        Args:
            automation_id: identificador da automação.
            wait: quando `True`, espera o disparo chegar a um estado terminal.

        Returns:
            O resumo do disparo manual e o seu desfecho.

        Raises:
            AutomationChatError: quando a automação não existe ou o disparo falha.
        """
        row = self._resolve(automation_id, None)
        dispatcher = Dispatcher(self._session)
        firing = dispatcher.dispatch_manual(row, tag="manual")
        if firing is None:
            raise AutomationChatError("não foi possível registrar o disparo")
        self._session.flush()
        outcome = await AutomationExecutor(self._session, self._settings).execute(firing)
        self._session.flush()
        if wait:
            await self._await_terminal(firing.id, timeout=120.0)
            self._session.refresh(firing)
        result: dict[str, Any] = {
            "success": True,
            "automation": self._summarize(row, brief=True),
            "firing": self._present_firing(firing),
            "outcome": {
                "state": outcome.state,
                "ok": outcome.ok,
                "detail": outcome.detail,
                "retry_at": outcome.retry_at.isoformat() if outcome.retry_at else None,
            },
            "runtime": self.runtime_status(),
        }
        result["message"] = self._describe_execution(result)
        return result

    def _describe_execution(self, result: dict[str, Any]) -> str:
        """Texto que separa os três estados: disparo registrado, run iniciado, objetivo concluído.

        Args:
            result: resultado da execução.

        Returns:
            A frase que descreve o que realmente aconteceu.
        """
        firing = result.get("firing") or {}
        outcome = result.get("outcome") or {}
        state = str(outcome.get("state") or firing.get("state") or "")
        detail = outcome.get("detail")
        run_id = firing.get("run_id")
        if state == "running":
            base = (
                "Disparo registrado e executado: o run foi criado e entregue ao worker "
                f"(run {run_id}). O objetivo ainda NÃO está concluído — o estado real "
                "está no histórico da automação."
            )
        elif state == "completed":
            base = f"Disparo concluído{': ' + str(detail) if detail else ''}."
        elif state in {"failed", "blocked"}:
            base = f"Disparo falhou ({state}){': ' + str(detail) if detail else ''}."
        elif state == "waiting_dependency":
            base = (
                "Disparo registrado, mas uma dependência está indisponível: "
                "o disparo foi reagendado sem inferência."
            )
        else:
            base = f"Disparo registrado (estado: {state or 'pendente'})."
        runtime = result.get("runtime") or {}
        if runtime.get("mode") == "sem_runtime":
            base += (
                " Atenção: nenhum runtime de automações está rodando agora — o disparo "
                "fica pendente até o Callidus (ou o `callidus-supervisor`) voltar."
            )
        return base

    async def _await_terminal(self, firing_id: uuid.UUID, *, timeout: float) -> None:
        """Espera o disparo alcançar um estado terminal.

        Args:
            firing_id: identificador do disparo.
            timeout: tempo máximo de espera, em segundos.
        """
        import asyncio

        deadline = asyncio.get_running_loop().time() + timeout
        terminal = {
            FiringState.COMPLETED.value,
            FiringState.FAILED.value,
            FiringState.CANCELLED.value,
            FiringState.BLOCKED.value,
            FiringState.SKIPPED.value,
        }
        while asyncio.get_running_loop().time() < deadline:
            row = self._session.get(AutomationFiringModel, firing_id)
            if row is None or row.state in terminal:
                return
            await asyncio.sleep(0.5)

    async def test(self, automation_id: str, *, execute: bool = False) -> dict[str, Any]:
        """Verifica a prontidão da automação e, opcionalmente, dispara um teste.

        Args:
            automation_id: identificador da automação.
            execute: quando `True`, o teste executa a ação de verdade.

        Returns:
            O resumo da verificação de prontidão (e do teste, quando executado).

        Raises:
            AutomationChatError: quando a automação não existe.
        """
        row = self._resolve(automation_id, None)
        readiness = await self._readiness(row)
        result: dict[str, Any] = {
            "success": True,
            "automation": self._summarize(row, brief=True),
            "readiness": readiness,
            "executed": False,
        }
        if not execute:
            result["message"] = (
                "Prontidão verificada sem executar nada. Use execute=true só quando o "
                "pedido for explicitamente um teste com efeito real."
            )
            return result
        dispatcher = Dispatcher(self._session)
        firing = dispatcher.dispatch_manual(row, tag="test")
        if firing is None:
            raise AutomationChatError("não foi possível registrar o teste")
        self._session.flush()
        outcome = await AutomationExecutor(self._session, self._settings).execute(firing)
        self._session.flush()
        result["executed"] = True
        result["firing"] = self._present_firing(firing)
        result["outcome"] = {
            "state": outcome.state,
            "ok": outcome.ok,
            "detail": outcome.detail,
            "retry_at": outcome.retry_at.isoformat() if outcome.retry_at else None,
        }
        result["runtime"] = self.runtime_status()
        result["message"] = self._describe_execution(result)
        return result

    def history(self, automation_id: str, *, limit: int = 20) -> dict[str, Any]:
        """Lista os disparos de uma automação, do mais recente para o mais antigo.

        Args:
            automation_id: identificador da automação.
            limit: número máximo de disparos devolvido.

        Returns:
            Dicionário com a lista de disparos.

        Raises:
            AutomationChatError: quando a automação não existe.
        """
        row = self._resolve(automation_id, None)
        firings = self._recent_firings(row.id, limit=limit)
        return {
            "success": True,
            "automation": self._summarize(row, brief=True),
            "count": len(firings),
            "firings": firings,
        }

    def cancel_pending(self, automation_id: str) -> dict[str, Any]:
        """Cancela os disparos pendentes de uma automação.

        Args:
            automation_id: identificador da automação.

        Returns:
            Dicionário com a quantidade de disparos cancelados.

        Raises:
            AutomationChatError: quando a automação não existe.
        """
        row = self._resolve(automation_id, None)
        rows = list(
            self._session.scalars(
                self._select_firings(row.id).where(
                    AutomationFiringModel.state.in_(
                        [
                            FiringState.PENDING.value,
                            FiringState.WAITING_DEPENDENCY.value,
                            FiringState.PREPARING.value,
                        ]
                    )
                )
            ).all()
        )
        for firing in rows:
            firing.state = FiringState.CANCELLED.value
            firing.error = "cancelado pelo usuário"
        self._session.flush()
        return {
            "success": True,
            "automation": self._summarize(row, brief=True),
            "cancelled": len(rows),
            "message": (
                f"{len(rows)} disparo(s) pendente(s) cancelado(s)."
                if rows
                else "Não havia disparo pendente."
            ),
        }

    def delete(self, automation_id: str, *, confirm: bool = False) -> dict[str, Any]:
        """Remove uma automação.

        Args:
            automation_id: identificador da automação.
            confirm: confirmação do usuário; sem ela, a remoção é recusada.

        Returns:
            Dicionário com a confirmação da remoção.

        Raises:
            AutomationChatError: quando a automação não existe ou falta a confirmação.
        """
        row = self._resolve(automation_id, None)
        if not confirm:
            raise AutomationChatError(
                "remover uma automação é definitivo: confirme com o usuário antes de "
                "chamar de novo com confirm=true",
                field="confirm",
                requires_confirmation=True,
            )
        name = row.name
        self._automations.delete(row.id)
        self._session.flush()
        return {
            "success": True,
            "deleted": True,
            "id": str(row.id),
            "name": name,
            "message": f"Automação «{name}» removida.",
        }

    # ------------------------------------------------------- diagnóstico

    def runtime_status(self) -> dict[str, Any]:
        """Estado do runtime de automações e do serviço nativo.

        Returns:
            Dicionário com o modo de execução, o serviço nativo e as limitações.
        """
        supervisor = self._supervisor()
        try:
            status = supervisor.status(session=self._session)
        except Exception as exc:  # noqa: BLE001 — diagnóstico não derruba o chat
            status = {"error": str(exc)}
        service: dict[str, Any] = {}
        try:
            from agent.automation.service import current_adapter

            service = current_adapter().status().as_dict()
        except Exception as exc:  # noqa: BLE001
            service = {"error": str(exc)}
        heartbeat = status.get("heartbeat") if isinstance(status, dict) else None
        alive = bool(heartbeat) and _heartbeat_is_fresh(heartbeat)
        native_active = bool(service.get("active"))
        if alive:
            mode = "runtime_vivo"
        elif native_active:
            mode = "servico_nativo"
        else:
            mode = "sem_runtime"
        limitations: list[str] = []
        if not alive and not native_active:
            limitations.append(
                "Nenhum runtime de automações está em execução agora: as automações "
                "habilitadas só vão disparar quando o Callidus estiver rodando "
                "(com a interface ou com `callidus-supervisor install`)."
            )
        if alive and not native_active:
            limitations.append(
                "O runtime está em execução junto com a interface: ao fechar o Callidus, "
                "os disparos param até o processo voltar."
            )
        return {
            "mode": mode,
            "supervisor_running": alive,
            "native_service": service,
            "stats": status.get("stats") if isinstance(status, dict) else None,
            "automations": status.get("automations") if isinstance(status, dict) else None,
            "next_run_at": status.get("next_run_at") if isinstance(status, dict) else None,
            "limitations": limitations,
            "recoverable": (
                "Disparos perdidos durante uma interrupção são recuperados conforme a "
                "política da automação (run_once, catch_up, group ou skip)."
            ),
        }

    def diagnose(self) -> dict[str, Any]:
        """Diagnóstico do runtime: automações, próximos disparos e pendências.

        Returns:
            O diagnóstico do supervisor, com as automações resumidas.
        """
        supervisor = self._supervisor()
        report = supervisor.diagnose(session=self._session)
        report["runtime"] = self.runtime_status()
        report["message"] = (
            "Diagnóstico do runtime: compare `next_run_at` (recalculado pelo gatilho) com "
            "`stored_next_run_at` (gravado no banco) para ver divergência de horário."
        )
        return report

    def _supervisor(self):
        """Supervisor ligado ao mesmo banco da conversa.

        Returns:
            O supervisor, com sessões próprias (nunca a sessão da conversa).
        """
        from agent.automation.supervisor import AutomationSupervisor
        from agent.persistence.database import build_session_factory

        engine = self._session.get_bind()
        factory = build_session_factory(engine)
        return AutomationSupervisor(self._settings, session_factory=factory)

    # ------------------------------------------------------------ apoio

    async def _readiness(self, row: AutomationModel) -> dict[str, Any]:
        """Verifica as dependências declaradas da automação.

        Args:
            row: automação verificada.

        Returns:
            O relatório de prontidão no formato do resolvedor de dependências.
        """
        project = self._session.get(ProjectModel, row.project_id)
        remote_row = self._session.get(ProjectRemoteModel, row.project_id)
        remote = dict(remote_row.config_json or {}) if remote_row else None
        resolver = DependencyResolver(
            settings=self._settings,
            project_root=project.root_path if project else None,
            remote=remote,
            target_kind=str(row.target_kind or TargetKind.LOCAL.value),
        )
        specs = [DependencySpec.model_validate(item) for item in (row.dependencies_json or [])]
        if not specs:
            return {"ok": True, "dependencies": [], "blocking": []}
        check = await resolver.check_all(specs)
        return check.as_dict()

    def _recent_firings(self, automation_id: uuid.UUID, *, limit: int = 20) -> list[dict[str, Any]]:
        """Disparos recentes de uma automação.

        Args:
            automation_id: identificador da automação.
            limit: número máximo devolvido.

        Returns:
            A lista de disparos serializados.
        """
        rows = list(
            self._session.scalars(
                self._select_firings(automation_id)
                .order_by(AutomationFiringModel.scheduled_for.desc())
                .limit(max(1, min(int(limit), 100)))
            ).all()
        )
        return [self._present_firing(row) for row in rows]

    def _select_firings(self, automation_id: uuid.UUID):
        """Consulta base dos disparos de uma automação.

        Args:
            automation_id: identificador da automação.

        Returns:
            A consulta SQLAlchemy.
        """
        from sqlalchemy import select

        return select(AutomationFiringModel).where(
            AutomationFiringModel.automation_id == automation_id
        )

    def _present_firing(self, row: AutomationFiringModel) -> dict[str, Any]:
        """Serializa um disparo.

        Args:
            row: registro do disparo.

        Returns:
            Dicionário com o estado, o horário, o run associado e o erro.
        """
        result = dict(row.result_json or {})
        return {
            "id": str(row.id),
            "state": row.state,
            "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
            "fired_at": row.fired_at.isoformat() if row.fired_at else None,
            "attempt": row.attempt,
            "max_attempts": row.max_attempts,
            "run_id": str(row.run_id) if row.run_id else None,
            "task_id": str(row.task_id) if row.task_id else None,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "error": row.error,
            "summary": result.get("summary"),
            "action": result.get("action"),
            "run_status": result.get("run_status"),
        }

    def _summarize(self, row: AutomationModel, *, brief: bool = False) -> dict[str, Any]:
        """Resumo estruturado de uma automação (sem objeto ORM).

        Args:
            row: registro da automação.
            brief: quando `True`, devolve só o essencial.

        Returns:
            Dicionário com o estado real da automação.
        """
        trigger = TriggerSpec.model_validate(row.trigger_json or {})
        action = dict(row.action_json or {})
        next_run = row.next_run_at
        # O próximo disparo gravado vale para as automações habilitadas; para as
        # desabilitadas, o previsto é calculado pelo gatilho — é o que a prévia
        # mostra ao usuário antes da confirmação.
        planned = self._automations.next_occurrence(row)
        summary: dict[str, Any] = {
            "id": str(row.id),
            "name": row.name,
            "state": row.state,
            "project_id": str(row.project_id),
            "timezone": row.timezone,
            "schedule": {
                "kind": trigger.kind.value,
                "cron": trigger.cron,
                "run_at": trigger.run_at.isoformat() if trigger.run_at else None,
                "interval_seconds": trigger.interval_seconds,
                "summary": describe_trigger(trigger, timezone=row.timezone),
            },
            "action": {
                "kind": action.get("kind"),
                "objective": action.get("objective"),
                "command": action.get("command"),
                "objective_mode": row.objective_mode,
            },
            "permissions": dict(row.permissions_json or {}),
            "dependencies": list(row.dependencies_json or []),
            "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "task_id": str(row.task_id) if row.task_id else None,
            "next_run_at": next_run.isoformat() if next_run else None,
            "next_run_at_local": _local_label(next_run, row.timezone),
            "planned_next_run_at": planned.isoformat() if planned else None,
            "planned_next_run_at_local": _local_label(planned, row.timezone),
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if brief:
            # O resumo curto leva o token de confirmação: é ele que permite ativar
            # a automação depois que o usuário confirma, e o modelo não tem outro
            # lugar para buscá-lo.
            summary["confirmation_token"] = self._confirmation_token(row)
            return summary
        summary["confirmation_token"] = self._confirmation_token(row)
        summary["needs_confirmation"] = row.state != AutomationState.ENABLED.value
        return summary

    def _confirmation_token(self, row: AutomationModel) -> str:
        """Token que liga a confirmação à definição apresentada.

        Args:
            row: registro da automação.

        Returns:
            O token (hash dos campos que definem a definição).
        """
        payload = {field: getattr(row, field) for field in _TOKEN_FIELDS}
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:32]

    def _resolve_timezone(self, timezone: str | None) -> str:
        """Fuso da automação: o pedido, o configurado ou o padrão documentado.

        Args:
            timezone: fuso pedido.

        Returns:
            O nome do fuso validado.

        Raises:
            AutomationChatError: quando o fuso pedido não existe.
        """
        candidate = timezone or getattr(self._settings, "automation_timezone", None) or DEFAULT_TIMEZONE
        try:
            return resolve_timezone(candidate)
        except ValueError as exc:
            raise AutomationChatError(str(exc), field="timezone") from exc


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Converte um valor em UUID, tolerando ausência e texto inválido.

    Args:
        value: valor de entrada.

    Returns:
        O UUID correspondente, ou `None`.
    """
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _normalize(text: str) -> str:
    """Texto em minúsculas e sem acentos, para comparar nomes.

    Args:
        text: texto de entrada.

    Returns:
        O texto normalizado.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return " ".join("".join(ch for ch in decomposed if not unicodedata.combining(ch)).split())


def _local_label(moment: datetime | None, timezone: str) -> str | None:
    """Instante no fuso local, em texto.

    Args:
        moment: instante a formatar.
        timezone: fuso de exibição.

    Returns:
        O texto `dd/mm/aaaa HH:MM`, ou `None`.
    """
    if moment is None:
        return None
    from zoneinfo import ZoneInfo

    try:
        local = moment.astimezone(ZoneInfo(resolve_timezone(timezone)))
    except Exception:  # noqa: BLE001 — fuso inválido não derruba a leitura
        return moment.isoformat()
    return local.strftime("%d/%m/%Y %H:%M")


def _parse_instant(value: str, timezone: str) -> datetime:
    """Converte um texto de instante em datetime com fuso.

    Args:
        value: texto ISO 8601 (ou `YYYY-MM-DD HH:MM`).
        timezone: fuso usado quando o texto não traz fuso.

    Returns:
        O instante, em UTC.

    Raises:
        AutomationChatError: quando o texto não é um instante válido.
    """
    from datetime import datetime as _dt

    from agent.automation.timezones import localize

    text = value.strip().replace("Z", "+00:00")
    try:
        moment = _dt.fromisoformat(text)
    except ValueError as exc:
        raise AutomationChatError(
            f"instante inválido: {value} (use o formato AAAA-MM-DD HH:MM)", field="run_at"
        ) from exc
    if moment.tzinfo is None:
        naive = moment
        return localize(naive, timezone)
    return moment.astimezone(timezone.utc)


def _heartbeat_is_fresh(heartbeat: dict[str, Any]) -> bool:
    """Diz se o batimento do runtime é recente.

    Args:
        heartbeat: payload do batimento.

    Returns:
        `True` quando o runtime escreveu há menos de dois minutos.
    """
    from datetime import datetime as _dt

    stamp = heartbeat.get("created_at") or heartbeat.get("last_tick_at")
    if not stamp:
        return False
    try:
        moment = _dt.fromisoformat(str(stamp))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - moment.astimezone(timezone.utc)).total_seconds()
    return 0 <= age < 120


__all__ = ["AutomationChatError", "AutomationChatService"]
