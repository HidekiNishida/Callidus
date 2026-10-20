"""
Arquivo: src/agent/automation/contracts.py
Nome: contracts.py
Propósito: definir e validar o contrato da definição de uma automação.
Responsabilidade: camada de domínio — modelos pydantic do documento que descreve a automação.
Componentes: TriggerSpec, CallidusAction, ScriptAction, ActionSpec, StartStrategy, DependencySpec, PermissionSpec, RecoveryPolicy, AutomationDefinition, parse_action, dump_action, CONTRACT_VERSION.
Dependências: pydantic, agent.automation.enums.
Observações: a versão do contrato permite ler o que foi gravado por versões anteriores.

Os contratos pydantic que dão forma à automação.

Uma automação aprovada é um documento: gatilho, ação, dependências, permissões e
política de recuperação. O documento é validado na entrada e gravado em JSON no
banco — a versão do contrato (`CONTRACT_VERSION`) permite ler o que foi gravado por
versões anteriores.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from agent.automation.enums import (
    ActionKind,
    DependencyKind,
    MissedPolicy,
    ObjectiveMode,
    StartMechanism,
    TargetKind,
    TriggerKind,
)

CONTRACT_VERSION = 1


class TriggerSpec(BaseModel):
    """Gatilho: quando a automação acorda."""

    kind: TriggerKind
    # `once`: instante único (UTC). `cron`: expressão de 5 ou 6 campos.
    # `interval`: período em segundos. `event`: tipo de evento procurado.
    run_at: datetime | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    event_type: str | None = None
    event_types: list[str] = Field(default_factory=list)
    event_filter: dict[str, Any] = Field(default_factory=dict)
    # Fuso do gatilho. Horários locais ambíguos ou inexistentes são tratados no cálculo.
    timezone: str = "UTC"
    # Política para disparos perdidos enquanto o runtime estava fora do ar.
    missed_policy: MissedPolicy = MissedPolicy.RUN_ONCE
    # Teto de recuperações quando a política é `catch_up` ou `group`.
    max_catch_up: int = 10

    @field_validator("timezone")
    @classmethod
    def _fuso_valido(cls, value: str) -> str:
        """Valida o fuso informado no gatilho.

        Args:
            value: nome do fuso.

        Returns:
            O fuso validado.

        Raises:
            ValueError: quando o fuso não existe.
        """
        from agent.automation.timezones import resolve_timezone

        return resolve_timezone(value)

    def model_post_init(self, _context: Any) -> None:  # noqa: D401
        """Confere que os campos exigidos pelo tipo de gatilho estão presentes.

        Raises:
            ValueError: quando falta o campo exigido pelo tipo escolhido.
        """
        if self.kind is TriggerKind.ONCE and self.run_at is None:
            raise ValueError("gatilho 'once' exige run_at")
        if self.kind is TriggerKind.CRON and not (self.cron or "").strip():
            raise ValueError("gatilho 'cron' exige cron")
        if self.kind is TriggerKind.INTERVAL and not (self.interval_seconds or 0) > 0:
            raise ValueError("gatilho 'interval' exige interval_seconds > 0")
        if self.kind is TriggerKind.EVENT and not (self.event_type or self.event_types):
            raise ValueError("gatilho 'event' exige event_type ou event_types")


class CallidusAction(BaseModel):
    """Ação Callidus: cria ou retoma um trabalho pelos serviços existentes."""

    kind: Literal[ActionKind.CALLIDUS] = ActionKind.CALLIDUS
    objective: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    objective_mode: ObjectiveMode = ObjectiveMode.FROZEN
    model_id: str | None = None
    provider: str | None = None
    # Entrega o run ao worker autônomo (o mesmo caminho de um run disparado pela interface).
    autonomous: bool = True
    timeout_sec: float | None = None
    # Espera o run terminar antes de fechar o disparo (usado em "executar agora" e teste).
    wait: bool = False
    wait_timeout_sec: float | None = None


class ScriptAction(BaseModel):
    """Ação de script: execução determinística, sem depender de inferência."""

    kind: Literal[ActionKind.SCRIPT] = ActionKind.SCRIPT
    command: list[str] = Field(default_factory=list)
    # Caminho do script quando `command` não traz o executável.
    script: str | None = None
    interpreter: str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    # Códigos de saída aceitos como sucesso (o padrão é só zero).
    success_exit_codes: list[int] = Field(default_factory=lambda: [0])
    timeout_sec: float | None = None
    # Texto que, se aparecer na saída, indica sucesso (opcional).
    success_regex: str | None = None
    # Arquivo que recebe o recibo do disparo. Se existir com a mesma chave, a ação
    # não repete o script (o efeito anterior já aconteceu).
    receipt_path: str | None = None

    @field_validator("command")
    @classmethod
    def _comando_lista(cls, value: list[str]) -> list[str]:
        """Normaliza o comando da ação de script em uma lista de textos não vazios.

        Args:
            value: comando informado.

        Returns:
            A lista normalizada.
        """
        return [str(item) for item in value if str(item).strip()]


ActionSpec = Annotated[CallidusAction | ScriptAction, Field(discriminator="kind")]

# A união discriminada não é um modelo: quem valida usa o adaptador.
_ACTION_ADAPTER = TypeAdapter(ActionSpec)


def parse_action(data: Any) -> CallidusAction | ScriptAction:
    """Valida um dicionário de ação (JSON persistido ou payload da API).

    Args:
        data: documento da ação.

    Returns:
        A ação validada, conforme o discriminador `kind`.

    Raises:
        ValidationError: quando o documento não corresponde a nenhum tipo de ação.
    """
    return _ACTION_ADAPTER.validate_python(data)


def dump_action(action: CallidusAction | ScriptAction) -> dict:
    """Serializa a ação para JSON (persistência).

    Args:
        action: ação a serializar.

    Returns:
        O documento JSON da ação.
    """
    return _ACTION_ADAPTER.dump_python(action, mode="json")


class StartStrategy(BaseModel):
    """Como iniciar a dependência quando ela não está pronta.

    Só é usado quando `authorized` é verdadeiro **e** o mecanismo está configurado.
    """

    mechanism: StartMechanism = StartMechanism.NONE
    authorized: bool = False
    # Comando de inicialização (interpretação conforme a plataforma do destino).
    command: list[str] = Field(default_factory=list)
    # Serviço nativo a reiniciar (`launchd`/`systemd`/`sc.exe`).
    service_name: str | None = None
    timeout_sec: float = 60.0
    max_retries: int = 2
    backoff_sec: float = 5.0


class DependencySpec(BaseModel):
    """Dependência que precisa estar pronta antes da ação rodar."""

    kind: DependencyKind
    name: str = ""
    # Parâmetros específicos do tipo (host, caminho, ferramenta, provedor...).
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    start: StartStrategy | None = None

    def label(self) -> str:
        """Rótulo legível da dependência, para mensagens e evidências.

        Returns:
            O nome informado ou, na falta dele, o tipo da dependência.
        """
        return self.name or self.kind.value


class PermissionSpec(BaseModel):
    """Permissões decididas antes do disparo — o modelo não as amplia durante a execução."""

    allow_scripts: bool = False
    # Prefixos de executável permitidos (ex.: `python3`, `/usr/bin/git`).
    allowed_commands: list[str] = Field(default_factory=list)
    # Raízes de diretório autorizadas para a ação.
    allowed_paths: list[str] = Field(default_factory=list)
    # Exige aprovação explícita para ações destrutivas.
    require_approval: bool = False
    destructive_allowed: bool = False
    # Recursos aprovados no momento da aprovação — fica registrado o que foi autorizado.
    approved_resources: list[str] = Field(default_factory=list)


class RecoveryPolicy(BaseModel):
    """Política de recuperação da ação."""

    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_sec: float | None = None
    backoff_sec: float = 10.0
    backoff_multiplier: float = 2.0
    max_backoff_sec: float = 900.0
    # Causas de falha que justificam nova tentativa.
    retry_on: list[str] = Field(
        default_factory=lambda: [
            "dependency_unavailable",
            "remote_unreachable",
            "timeout",
            "interrupted",
        ]
    )
    # Volta a tentar sozinho quando a dependência voltar a ficar disponível.
    resume_on_dependency: bool = True


class AutomationDefinition(BaseModel):
    """Definição completa de uma automação — o que a API e a interface enviam."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    project_id: str
    contract_version: int = CONTRACT_VERSION
    target_kind: TargetKind = TargetKind.LOCAL
    trigger: TriggerSpec
    action: ActionSpec
    dependencies: list[DependencySpec] = Field(default_factory=list)
    permissions: PermissionSpec = Field(default_factory=PermissionSpec)
    policy: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    timezone: str = "UTC"
    missed_policy: MissedPolicy = MissedPolicy.RUN_ONCE
    conversation_id: str | None = None
    task_id: str | None = None
    objective_mode: ObjectiveMode = ObjectiveMode.FROZEN
    state: str = "disabled"

    @field_validator("timezone")
    @classmethod
    def _fuso_valido(cls, value: str) -> str:
        """Valida o fuso informado na definição.

        Args:
            value: nome do fuso.

        Returns:
            O fuso validado.

        Raises:
            ValueError: quando o fuso não existe.
        """
        from agent.automation.timezones import resolve_timezone

        return resolve_timezone(value)


__all__ = [
    "CONTRACT_VERSION",
    "dump_action",
    "parse_action",
    "ActionSpec",
    "AutomationDefinition",
    "CallidusAction",
    "DependencySpec",
    "PermissionSpec",
    "RecoveryPolicy",
    "ScriptAction",
    "StartStrategy",
    "TriggerSpec",
]
