"""
Arquivo: src/agent/memory/layers.py
Nome: layers.py
Propósito: recuperação de memória por camada (imediata, tarefa, projeto, arquivo histórico).
Responsabilidade: camada de aplicação — organiza a memória por finalidade e custo de recuperação,
evitando carregar todas as camadas em todas as inferências.
Componentes: MemoryLayer, MemoryLayers.
Dependências: agent.domain.enums, agent.memory.operational, agent.persistence.models, sqlalchemy, uuid.
Observações: não cria novas tabelas; lê de MemoryRecordModel com filtro por kind, escopo e tarefa.
A camada imediata é o nível 1 da memória operacional; a de tarefa agrega detalhes e artefatos;
a do projeto agrega memórias canônicas/contextuais; o arquivo histórico preserva registros extensos
recuperados somente quando necessário.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from sqlalchemy import or_, select

from agent.domain.enums import MemoryKind
from agent.memory.operational import recall, render_for_prompt
from agent.persistence.models import MemoryRecordModel, TaskModel

_LAYER_UNKNOWN = "camada de memória desconhecida: {name}"

#: Kinds que compõem a memória imediata (nível 1 da tarefa).
_IMMEDIATE_KINDS = (MemoryKind.OPERATIONAL.value,)

#: Kinds que compõem a memória da tarefa (níveis 1, 2 e 3).
_TASK_KINDS = (
    MemoryKind.OPERATIONAL.value,
    MemoryKind.TASK_DETAIL.value,
    MemoryKind.ARTIFACT.value,
)

#: Kinds que compõem a memória do projeto (escopo de projeto, sem tarefa fixa).
_PROJECT_KINDS = (
    MemoryKind.CANONICAL.value,
    MemoryKind.CONTEXTUAL.value,
    MemoryKind.EVIDENCE.value,
    MemoryKind.PROCEDURE.value,
)

#: Kinds que vão para o arquivo histórico (registros extensos e versões antigas).
_ARCHIVE_KINDS = (MemoryKind.EXECUTION.value,)


class MemoryLayer(str):
    """Camada de memória com propósito e custo de recuperação definidos.

    Atributos:
        name: identificador da camada (`immediate`, `task`, `project`, `archive`).
        purpose: descrição do que a camada contém.
        cost: custo relativo de recuperação (`baixo`, `medio`, `alto`).
    """

    __slots__ = ("cost", "name", "purpose")

    IMMEDIATE = "immediate"
    TASK = "task"
    PROJECT = "project"
    ARCHIVE = "archive"

    _META: dict[str, tuple[str, str]] = {
        IMMEDIATE: ("só o necessário para a operação atual", "baixo"),
        TASK: ("plano, subtarefas, decisões, arquivos, erros anteriores", "medio"),
        PROJECT: ("arquitetura, subsistemas, contratos, convenções, testes relevantes", "medio"),
        ARCHIVE: ("registros extensos e resultados brutos, recuperados sob demanda", "alto"),
    }

    def __init__(self, name: str) -> None:
        purpose, cost = self._META.get(name, ("camada de memória", "medio"))
        self.name = name
        self.purpose = purpose
        self.cost = cost

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MemoryLayer):
            return self.name == other.name
        return self.name == other

    def __hash__(self) -> int:
        return hash(self.name)


class MemoryLayers:
    """Recuperação de memória por camada.

    Cada camada é recuperada separadamente e só quando necessária, de modo que
    uma inferência de operação pequena não pague por memória de projeto inteira.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
        """
        self._session = session

    def immediate(self, task_id: Any, *, objective: str = "", limit: int = 1) -> list[MemoryRecordModel]:
        """Memória imediata: nível 1 da tarefa (estado atual e próximo passo).

        Args:
            task_id: identificador da tarefa.
            objective: objetivo atual (usado para filtrar por relevância quando houver vários).
            limit: máximo de registros devolvidos.

        Returns:
            Os registros de memória imediata, mais recentes primeiro.
        """
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return []
        return recall(
            self._session,
            project_id=task.project_id,
            task_id=task_id,
            kind=MemoryKind.OPERATIONAL.value,
            text=objective or None,
            limit=limit,
        )

    def task(
        self,
        *,
        project_id: Any,
        task_id: Any | None = None,
        parent_task_id: Any | None = None,
        kind: str | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecordModel]:
        """Memória da tarefa: plano, subtarefas, decisões, arquivos, erros anteriores.

        Args:
            project_id: projeto dono dos registros.
            task_id: restringe a uma tarefa específica.
            parent_task_id: inclui a tarefa e as filhas diretas.
            kind: filtra por kind (`operational`, `task_detail`, `artifact`).
            text: trecho procurado no título, resumo ou conteúdo.
            limit: máximo de registros devolvidos.

        Returns:
            Os registros de memória da tarefa, mais recentes primeiro.
        """
        return recall(
            self._session,
            project_id=project_id,
            task_id=task_id,
            parent_task_id=parent_task_id,
            kind=kind,
            text=text,
            limit=limit,
        )

    def project(
        self,
        *,
        project_id: Any,
        kind: str | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecordModel]:
        """Memória do projeto: arquitetura, subsistemas, contratos, convenções, testes relevantes.

        Argumentos com `conversation_id` nulo são memória de projeto; com conversa preenchida são
        memória de conversa (não entram aqui, a menos que `kind` seja específico).

        Args:
            project_id: projeto dono dos registros.
            kind: filtra por kind (`canonical`, `contextual`, `evidence`, `procedure`).
            text: trecho procurado no título, resumo ou conteúdo.
            limit: máximo de registros devolvidos.

        Returns:
            Os registros de memória do projeto, mais recentes primeiro.
        """
        stmt = select(MemoryRecordModel).where(
            MemoryRecordModel.project_id == project_id,
            MemoryRecordModel.conversation_id.is_(None),
        )
        if kind:
            stmt = stmt.where(MemoryRecordModel.kind == kind)
        needle = (text or "").strip()
        if needle:
            stmt = stmt.where(
                or_(
                    MemoryRecordModel.title.contains(needle),
                    MemoryRecordModel.summary.contains(needle),
                    MemoryRecordModel.content.contains(needle),
                )
            )
        stmt = stmt.order_by(MemoryRecordModel.created_at.desc()).limit(max(1, min(limit, 50)))
        return list(self._session.scalars(stmt).all())

    def archive(
        self,
        *,
        project_id: Any,
        kind: str | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecordModel]:
        """Arquivo histórico: registros extensos e resultados brutos, recuperados somente quando necessário.

        Args:
            project_id: projeto dono dos registros.
            kind: filtra por kind (`execution`, ou outro quando informado).
            text: trecho procurado no título, resumo ou conteúdo.
            limit: máximo de registros devolvidos.

        Returns:
            Os registros do arquivo histórico, mais recentes primeiro.
        """
        stmt = select(MemoryRecordModel).where(
            MemoryRecordModel.project_id == project_id,
        )
        if kind:
            stmt = stmt.where(MemoryRecordModel.kind == kind)
        else:
            stmt = stmt.where(MemoryRecordModel.kind.in_(_ARCHIVE_KINDS))
        needle = (text or "").strip()
        if needle:
            stmt = stmt.where(
                or_(
                    MemoryRecordModel.title.contains(needle),
                    MemoryRecordModel.summary.contains(needle),
                    MemoryRecordModel.content.contains(needle),
                )
            )
        stmt = stmt.order_by(MemoryRecordModel.created_at.desc()).limit(max(1, min(limit, 50)))
        return list(self._session.scalars(stmt).all())

    def layer(self, name: str) -> MemoryLayer:
        """Devolve o objeto de camada pelo nome.

        Args:
            name: `immediate`, `task`, `project` ou `archive`.

        Returns:
            A `MemoryLayer` correspondente.

        Raises:
            KeyError: quando o nome não é uma camada conhecida.
        """
        meta = MemoryLayer._META.get(name)
        if meta is None:
            raise KeyError(_LAYER_UNKNOWN.format(name=name))
        return MemoryLayer(name)

    def summary_for_prompt(self, task: TaskModel, *, layer_budget: int = 480) -> str:
        """Resumo enxuto da memória imediata da tarefa, pronto para o prompt.

        Usa o nível 1 da memória operacional, já comprimido pelo orçamento informado.

        Args:
            task: tarefa em execução.
            layer_budget: orçamento de caracteres do resumo.

        Returns:
            O resumo de memória imediata, ou vazio quando não há registro.
        """
        return render_for_prompt(self._session, task)[:layer_budget]
