"""
Arquivo: src/agent/services/conversation_service.py
Nome: conversation_service.py
Propósito: manter as conversas do usuário, dentro de projetos ou soltas na caixa de entrada.
Responsabilidade: camada de aplicação — criação, movimentação, ramificação e remoção de conversas.
Componentes: ConversationService, locale_for_task.
Dependências: agent.domain.schemas, agent.i18n.locale, agent.persistence.models, agent.services.branches.
Observações: uma conversa sem projeto vive na caixa de entrada, cuja raiz é a pasta do usuário.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from pathlib import Path

from agent.domain.enums import TaskKind
from agent.domain.schemas import ConversationCreate, ProjectCreate, TaskCreate
from agent.i18n.locale import detect_language
from agent.persistence.models import (
    BranchModel,
    ContextSnapshotModel,
    ConversationModel,
    EventLogModel,
    EvidenceModel,
    ExecutionRunModel,
    MemoryRecordModel,
    OperationAttemptModel,
    ProjectModel,
    TaskContractModel,
    TaskDependencyModel,
    TaskModel,
    utcnow,
)
from agent.services.branches import visible_tasks
from agent.services.cascade import delete_cascade
from agent.services.inbox import INBOX_ROOT, is_inbox_project, user_home
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService

_GENERIC_TITLES = {"Nova conversa", "New chat", "Nueva conversación"}


class ConversationService:
    """Operações sobre as conversas e seus ramos.

    Atributos:
        _session: sessão usada nas leituras, gravações e no registro de eventos.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    def list_conversations(self, project_id: uuid.UUID) -> list[ConversationModel]:
        """Conversas de um projeto, da mais recente para a mais antiga.

        Args:
            project_id: projeto consultado.

        Returns:
            A lista de conversas do projeto.
        """
        self._backfill(project_id)
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.project_id == project_id)
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def list_loose(self) -> list[ConversationModel]:
        """Conversas soltas, que vivem na caixa de entrada.

        Returns:
            A lista de conversas sem projeto; vazia quando não há caixa de entrada.
        """
        inbox = self._find_inbox()
        if inbox is None:
            return []
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.project_id == inbox.id)
            .order_by(ConversationModel.updated_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def create_loose(self, data: ConversationCreate) -> ConversationModel:
        """Cria uma conversa solta, garantindo a existência da caixa de entrada.

        Args:
            data: dados da conversa.

        Returns:
            A conversa criada.
        """
        return self.create_conversation(self._ensure_inbox().id, data)

    def move_conversation(
        self, conversation_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> ConversationModel:
        """Move uma conversa (e o que pertence a ela) para outro projeto.

        Args:
            conversation_id: identificador da conversa.
            project_id: projeto de destino; `None` devolve a conversa para a caixa de entrada.

        Returns:
            A conversa movida.

        Raises:
            LookupError: quando a conversa ou o projeto de destino não existem.
        """
        conversation = self.get_conversation(conversation_id)
        if project_id is None:
            target = self._ensure_inbox()
        else:
            target = ProjectService(self._session).get_project(project_id)
            if is_inbox_project(target):
                target = self._ensure_inbox()
        if conversation.project_id == target.id:
            return conversation
        tasks = list(
            self._session.scalars(
                select(TaskModel).where(TaskModel.conversation_id == conversation.id)
            ).all()
        )
        task_ids = [task.id for task in tasks]
        for task in tasks:
            task.project_id = target.id
        if task_ids:
            runs = list(
                self._session.scalars(
                    select(ExecutionRunModel).where(ExecutionRunModel.root_task_id.in_(task_ids))
                ).all()
            )
            for run in runs:
                run.project_id = target.id
        memories = list(
            self._session.scalars(
                select(MemoryRecordModel).where(MemoryRecordModel.conversation_id == conversation.id)
            ).all()
        )
        for memory in memories:
            memory.project_id = target.id
        conversation.project_id = target.id
        conversation.updated_at = utcnow()
        self._session.flush()
        return conversation

    def delete_conversation(self, conversation_id: uuid.UUID) -> None:
        """Remove a conversa e tudo que depende dela (tarefas, execuções, tentativas, evidências,
        eventos, memória e ramos). A ordem vem do grafo de chaves estrangeiras, então nenhuma
        FOREIGN KEY é violada."""
        conversation = self.get_conversation(conversation_id)
        # Ramos apontam para a conversa e para tarefas: solta antes de remover.
        branches = list(
            self._session.scalars(
                select(BranchModel).where(BranchModel.conversation_id == conversation.id)
            ).all()
        )
        for branch in branches:
            branch.parent_id = None
            branch.fork_task_id = None
        if branches:
            self._session.flush()
        delete_cascade(self._session, "conversations", conversation.id)
        self._session.flush()

    def create_conversation(self, project_id: uuid.UUID, data: ConversationCreate) -> ConversationModel:
        """Cria uma conversa dentro de um projeto, já com o primeiro ramo.

        Args:
            project_id: projeto dono da conversa.
            data: título e idioma da conversa.

        Returns:
            A conversa criada.
        """
        title = (data.title or "Nova conversa").strip()[:200] or "Nova conversa"
        locale = data.locale if data.locale in {"pt", "en", "es"} else "pt"
        conversation = ConversationModel(project_id=project_id, title=title, locale=locale)
        self._session.add(conversation)
        self._session.flush()
        self.ensure_branch(conversation)
        return conversation

    def get_conversation(self, conversation_id: uuid.UUID) -> ConversationModel:
        """Conversa por identificador.

        Args:
            conversation_id: identificador da conversa.

        Returns:
            A conversa encontrada.

        Raises:
            LookupError: quando a conversa não existe.
        """
        conversation = self._session.get(ConversationModel, conversation_id)
        if conversation is None:
            raise LookupError(f"Conversa não encontrada: {conversation_id}")
        return conversation

    def rename(self, conversation_id: uuid.UUID, title: str) -> ConversationModel:
        """Renomeia uma conversa.

        Args:
            conversation_id: identificador da conversa.
            title: novo título.

        Returns:
            A conversa renomeada.

        Raises:
            LookupError: quando a conversa não existe.
        """
        conversation = self.get_conversation(conversation_id)
        cleaned = title.strip()[:200]
        if cleaned:
            conversation.title = cleaned
            conversation.updated_at = utcnow()
            self._session.flush()
        return conversation

    def set_root(self, conversation_id: uuid.UUID, root_path: str | None) -> ConversationModel:
        """Define a pasta de trabalho da conversa.

        Args:
            conversation_id: identificador da conversa.
            root_path: pasta escolhida; `None` volta à raiz do projeto.

        Returns:
            A conversa atualizada.

        Raises:
            LookupError: quando a conversa não existe.
            ValueError: quando a pasta informada não existe.
        """
        conversation = self.get_conversation(conversation_id)
        if root_path is None or not root_path.strip():
            conversation.root_path = None
        else:
            path = Path(root_path).expanduser().resolve()
            if not path.is_dir():
                raise ValueError("a pasta não existe")
            conversation.root_path = str(path)
        conversation.updated_at = utcnow()
        self._session.flush()
        return conversation

    def ensure_branch(self, conversation: ConversationModel) -> BranchModel:
        """Garante que a conversa tenha um ramo ativo, herdando as tarefas soltas.

        Args:
            conversation: conversa que precisa de ramo.

        Returns:
            O ramo ativo da conversa.
        """
        if conversation.active_branch_id:
            current = self._session.get(BranchModel, conversation.active_branch_id)
            if current is not None:
                return current
        branch = BranchModel(conversation_id=conversation.id)
        self._session.add(branch)
        self._session.flush()
        conversation.active_branch_id = branch.id
        tasks = list(
            self._session.scalars(
                select(TaskModel).where(
                    TaskModel.conversation_id == conversation.id,
                    TaskModel.branch_id.is_(None),
                )
            ).all()
        )
        for task in tasks:
            task.branch_id = branch.id
        self._session.flush()
        return branch

    def branches_of(self, conversation_id: uuid.UUID) -> list[BranchModel]:
        """Ramos de uma conversa, do mais antigo ao mais recente.

        Args:
            conversation_id: identificador da conversa.

        Returns:
            A lista de ramos da conversa.
        """
        return list(
            self._session.scalars(
                select(BranchModel)
                .where(BranchModel.conversation_id == conversation_id)
                .order_by(BranchModel.created_at)
            ).all()
        )

    def activate_branch(self, conversation_id: uuid.UUID, branch_id: uuid.UUID) -> ConversationModel:
        """Ativa um ramo da conversa.

        Args:
            conversation_id: identificador da conversa.
            branch_id: identificador do ramo a ativar.

        Returns:
            A conversa com o ramo ativo atualizado.

        Raises:
            LookupError: quando a conversa ou o ramo não existem.
        """
        conversation = self.get_conversation(conversation_id)
        branch = self._session.get(BranchModel, branch_id)
        if branch is None or branch.conversation_id != conversation.id:
            raise LookupError("Ramo não encontrado")
        conversation.active_branch_id = branch.id
        conversation.updated_at = utcnow()
        self._session.flush()
        return conversation

    def tasks_for_branch(self, conversation_id: uuid.UUID, branch_id: uuid.UUID | None = None) -> list[TaskModel]:
        """Tarefas visíveis no ramo escolhido (o ativo, por padrão).

        Args:
            conversation_id: identificador da conversa.
            branch_id: ramo a consultar; `None` usa o ramo ativo.

        Returns:
            A lista de tarefas visíveis no ramo.

        Raises:
            LookupError: quando a conversa não existe.
        """
        conversation = self.get_conversation(conversation_id)
        self.ensure_branch(conversation)
        chosen = branch_id or conversation.active_branch_id
        branch = self._session.get(BranchModel, chosen)
        tasks = list(
            self._session.scalars(
                select(TaskModel).where(TaskModel.conversation_id == conversation.id)
            ).all()
        )
        if branch is None:
            return tasks
        catalog = {item.id: item for item in self.branches_of(conversation.id)}
        return visible_tasks(tasks, branch, catalog)

    def fork_message(self, conversation_id: uuid.UUID, task_id: uuid.UUID, objective: str) -> TaskModel:
        """Cria um ramo novo a partir de uma mensagem, com a tarefa do objetivo pedido.

        Args:
            conversation_id: identificador da conversa.
            task_id: mensagem a partir da qual bifurcar.
            objective: objetivo da nova linha de trabalho.

        Returns:
            A tarefa raiz do novo ramo.

        Raises:
            LookupError: quando a conversa ou a mensagem não existem.
        """
        conversation = self.get_conversation(conversation_id)
        task = self._session.get(TaskModel, task_id)
        if task is None or task.conversation_id != conversation.id or task.parent_id is not None:
            raise LookupError("Mensagem não encontrada nesta conversa")
        parent_branch = task.branch_id or self.ensure_branch(conversation).id
        branch = BranchModel(
            conversation_id=conversation.id,
            parent_id=parent_branch,
            fork_task_id=task.id,
        )
        self._session.add(branch)
        self._session.flush()
        conversation.active_branch_id = branch.id
        conversation.updated_at = utcnow()
        created = TaskService(self._session).create_task(
            conversation.project_id,
            TaskCreate(
                title=objective.strip()[:80] or task.title,
                objective=objective.strip(),
                conversation_id=conversation.id,
                branch_id=branch.id,
                kind=TaskKind.OBJECTIVE,
            ),
        )
        self._session.flush()
        return created

    def touch_title(self, conversation_id: uuid.UUID, title: str, locale: str) -> None:
        """Ajusta o título genérico e o idioma da conversa, sem sobrescrever títulos reais.

        Args:
            conversation_id: identificador da conversa.
            title: título calculado a partir do pedido.
            locale: idioma detectado.

        Raises:
            LookupError: quando a conversa não existe.
        """
        conversation = self.get_conversation(conversation_id)
        if conversation.title in _GENERIC_TITLES:
            conversation.title = title.strip()[:200] or conversation.title
        if locale in {"pt", "en", "es"}:
            conversation.locale = locale
        self._session.flush()

    def _find_inbox(self) -> ProjectModel | None:
        """Projeto da caixa de entrada, se existir.

        Returns:
            O projeto da caixa de entrada, ou `None` quando ele ainda não foi criado.
        """
        found = self._session.scalar(select(ProjectModel).where(ProjectModel.root_path == INBOX_ROOT))
        if found is None:
            found = self._session.scalar(select(ProjectModel).where(ProjectModel.path_origin == "inbox"))
        if found is None:
            return None
        if found.path_origin != "inbox" or is_inbox_project(found) and found.root_path == INBOX_ROOT:
            found.root_path = user_home()
            found.path_origin = "inbox"
            self._session.flush()
        return found

    def _ensure_inbox(self) -> ProjectModel:
        """Projeto da caixa de entrada, criado quando ainda não existe.

        Returns:
            O projeto da caixa de entrada.
        """
        found = self._find_inbox()
        if found is not None:
            return found
        return ProjectService(self._session).create_project(
            ProjectCreate(name="Conversas soltas", root_path=user_home(), description="inbox"),
            origin="inbox",
        )

    def _backfill(self, project_id: uuid.UUID) -> None:
        """Cria conversas para as tarefas raiz que ainda não têm conversa.

        Args:
            project_id: projeto varrido.
        """
        roots = list(
            self._session.scalars(
                select(TaskModel).where(
                    TaskModel.project_id == project_id,
                    TaskModel.parent_id.is_(None),
                    TaskModel.conversation_id.is_(None),
                )
            ).all()
        )
        for root in roots:
            locale = (root.metadata_json or {}).get("locale") or detect_language(root.objective or root.title)
            conversation = ConversationModel(
                project_id=project_id,
                title=(root.title or "Conversa")[:200],
                locale=locale if locale in {"pt", "en", "es"} else "pt",
            )
            self._session.add(conversation)
            self._session.flush()
            self._assign(root, conversation.id)

    def _assign(self, task: TaskModel, conversation_id: uuid.UUID) -> None:
        """Atribui a conversa à tarefa e a toda a sua subárvore.

        Args:
            task: tarefa raiz do grupo.
            conversation_id: conversa destino.
        """
        task.conversation_id = conversation_id
        children = list(
            self._session.scalars(select(TaskModel).where(TaskModel.parent_id == task.id)).all()
        )
        for child in children:
            self._assign(child, conversation_id)


def locale_for_task(session: Session, task: TaskModel | None) -> str:
    """Idioma da tarefa, herdado da conversa da raiz ou detectado no texto.

    Args:
        session: sessão usada na leitura da conversa.
        task: tarefa consultada.

    Returns:
        O código de idioma (`pt`, `en` ou `es`).
    """
    if task is None:
        return "pt"
    current = task
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.parent_id is None:
            break
        current = session.get(TaskModel, current.parent_id)
    root = current or task
    if root.conversation_id is not None:
        conversation = session.get(ConversationModel, root.conversation_id)
        if conversation is not None and conversation.locale:
            return conversation.locale
    meta = root.metadata_json or {}
    if meta.get("locale") in {"pt", "en", "es"}:
        return str(meta["locale"])
    return detect_language(root.objective or root.title or "")
