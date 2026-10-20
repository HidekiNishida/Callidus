"""
Arquivo: src/agent/orchestrator/execution/runtime.py
Nome: runtime.py
Propósito: agrupar os colaboradores que a execução de uma tarefa precisa.
Responsabilidade: camada de aplicação — contrato de dependências do executor; não contém regra de negócio.
Componentes: ExecutionRuntime (dataclass).
Dependências: agent.services.task_service, agent.services.attempt_service, agent.tools.registry, agent.config.
Observações: o executor, o modelo e o orquestrador compartilham a mesma instância — assim há um único registro de ferramentas e uma única contagem de tentativas por run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from agent.config import Settings
from agent.providers.base import LLMProvider
from agent.services.attempt_service import AttemptService
from agent.services.task_service import TaskService
from agent.tools.registry import ToolRegistry, build_default_registry


@dataclass(frozen=True)
class ExecutionRuntime:
    """Colaboradores compartilhados por quem executa uma tarefa.

    Atributos:
        session: sessão SQLAlchemy aberta; toda escrita da execução passa por ela.
        settings: configuração do processo (limites, caminhos, orçamento).
        tasks: serviço de tarefas — transições de estado e dependências.
        attempts: registro de tentativas — contagem, dedup e fingerprint de prompt.
        tools: registro de ferramentas determinísticas disponíveis ao agente.

    Observações:
        A instância é compartilhada (não copiada) entre o executor e o modelo: duplicá-la
        criaria dois registros de ferramentas e duas contagens de tentativas para o mesmo run.
    """

    session: Session
    settings: Settings
    tasks: TaskService
    attempts: AttemptService
    tools: ToolRegistry
    provider_factory: Callable[[Settings, dict], LLMProvider] | None = None

    @classmethod
    def build(
        cls,
        session: Session,
        settings: Settings | None = None,
        *,
        tasks: TaskService | None = None,
        attempts: AttemptService | None = None,
        tools: ToolRegistry | None = None,
        provider_factory: Callable[[Settings, dict], LLMProvider] | None = None,
    ) -> ExecutionRuntime:
        """Cria o conjunto de colaboradores de uma execução.

        Args:
            session: sessão SQLAlchemy em uso.
            settings: configuração do processo; quando ausente, usa os padrões de `Settings`.
            tasks: serviço de tarefas a reutilizar; quando ausente, cria um novo.
            attempts: registro de tentativas a reutilizar; quando ausente, cria um novo.
            tools: registro de ferramentas a reutilizar; quando ausente, cria o padrão.

        Returns:
            O `ExecutionRuntime` pronto para uso.
        """
        resolved = settings or Settings()
        return cls(
            session=session,
            settings=resolved,
            tasks=tasks or TaskService(session),
            attempts=attempts or AttemptService(session, max_attempts=resolved.max_attempts_per_task),
            tools=tools or build_default_registry(),
            provider_factory=provider_factory,
        )
