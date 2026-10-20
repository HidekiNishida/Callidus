"""
Arquivo: src/agent/services/project_service.py
Nome: project_service.py
Propósito: manter os projetos do usuário e a memória canônica que nasce com eles.
Responsabilidade: camada de aplicação — criação, alteração, remoção e memória inicial dos projetos.
Componentes: ProjectService.
Dependências: agent.domain.enums, agent.domain.schemas, agent.memory.store, agent.persistence.models, agent.services.cascade.
Observações: remover um projeto não apaga os arquivos da pasta; a interface deixa isso explícito.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.domain.enums import MemoryKind
from agent.domain.schemas import MemoryCreate, ProjectCreate
from agent.memory.store import structure_memory
from agent.persistence.models import (
    ConversationModel,
    EventLogModel,
    MemoryRecordModel,
    ProjectModel,
    ProjectRemoteModel,
)
from agent.services.cascade import delete_cascade
from agent.services.inbox import is_inbox_path, is_inbox_project, user_home


def _is_leaked_test_project(root_path: str) -> bool:
    """Indica se um caminho pertence a um projeto temporário de teste.

    Args:
        root_path: raiz do projeto.

    Returns:
        `True` quando o caminho é de teste ou da caixa de entrada.
    """
    path = root_path.replace("\\", "/")
    return "pytest-of-" in path or "/T/pytest-" in path or is_inbox_path(path)


class ProjectService:
    """Operações sobre os projetos do usuário.

    Atributos:
        _session: sessão usada nas leituras e gravações.
    """

    def __init__(self, session: Session) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
        """
        self._session = session

    def create_project(self, data: ProjectCreate, *, origin: str | None = None) -> ProjectModel:
        """Cria um projeto com a pasta de trabalho definida.

        Args:
            data: dados do projeto.
            origin: origem da pasta (`inbox`, `chosen` ou `home`).

        Returns:
            O projeto criado, com o fato `project.created` registrado.
        """
        raw = (data.root_path or "").strip()
        if origin == "inbox":
            root = user_home()
            path_origin = "inbox"
        elif not raw:
            root = user_home()
            path_origin = "home"
        else:
            root = str(Path(raw).expanduser().resolve())
            path_origin = origin or "chosen"
        project = ProjectModel(
            name=data.name,
            root_path=root,
            description=data.description,
            path_origin=path_origin,
        )
        self._session.add(project)
        self._session.flush()
        self._session.add(
            EventLogModel(
                project_id=project.id,
                event_type="project.created",
                payload_json={"name": project.name, "root_path": project.root_path},
            )
        )
        return project

    def update_project(self, project_id: uuid.UUID, *, name: str | None = None, root_path: str | None = None) -> ProjectModel:
        """Altera o nome ou a pasta de trabalho de um projeto.

        Args:
            project_id: identificador do projeto.
            name: novo nome do projeto.
            root_path: nova pasta de trabalho.

        Returns:
            O projeto atualizado.

        Raises:
            LookupError: quando o projeto não existe.
            ValueError: quando a pasta não existe ou o projeto é a caixa de entrada.
        """
        project = self.get_project(project_id)
        if is_inbox_project(project):
            raise ValueError("a pasta das conversas soltas não se altera por aqui")
        if name is not None and name.strip():
            project.name = name.strip()[:200]
        if root_path is not None:
            raw = root_path.strip()
            if not raw:
                project.root_path = user_home()
                project.path_origin = "home"
            else:
                path = Path(raw).expanduser().resolve()
                if not path.is_dir():
                    raise ValueError("a pasta não existe")
                project.root_path = str(path)
                project.path_origin = "chosen"
        self._session.flush()
        return project

    def get_remote(self, project_id: uuid.UUID) -> dict | None:
        """Configuração do computador remoto do projeto (None quando o projeto é local).

        Args:
            project_id: identificador do projeto.

        Returns:
            A configuração remota, ou `None` quando o projeto roda localmente.
        """
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            return None
        return dict(row.config_json or {})

    def set_remote(self, project_id: uuid.UUID, config: dict) -> dict:
        """Grava a configuração do computador remoto do projeto.

        Args:
            project_id: identificador do projeto.
            config: configuração remota.

        Returns:
            A configuração gravada.

        Raises:
            LookupError: quando o projeto não existe.
        """
        self.get_project(project_id)
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            row = ProjectRemoteModel(project_id=project_id, config_json=dict(config))
            self._session.add(row)
        else:
            row.config_json = dict(config)
        self._session.flush()
        return dict(config)

    def clear_remote(self, project_id: uuid.UUID) -> bool:
        """Remove a configuração do computador remoto do projeto.

        Args:
            project_id: identificador do projeto.

        Returns:
            `True` quando havia configuração e ela foi removida.
        """
        row = self._session.get(ProjectRemoteModel, project_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def list_projects(self) -> list[ProjectModel]:
        """Projetos visíveis para o usuário, do mais antigo ao mais novo.

        Returns:
            A lista de projetos, sem os temporários de teste e sem a caixa de entrada.
        """
        rows = list(self._session.scalars(select(ProjectModel).order_by(ProjectModel.created_at)).all())
        return [p for p in rows if not _is_leaked_test_project(p.root_path) and not is_inbox_project(p)]

    def delete_project(self, project_id: uuid.UUID) -> dict:
        """Remove o projeto e tudo que pertence a ele: conversas, tarefas, execuções, eventos,
        memória e o grafo de conhecimento. A remoção em cascata segue o grafo de chaves
        estrangeiras, então nada fica pendurado. Os arquivos da pasta do projeto **não** são
        apagados — a interface deixa isso explícito."""
        project = self.get_project(project_id)
        if is_inbox_project(project):
            raise ValueError("a pasta das conversas soltas não se remove por aqui")

        conversations = list(
            self._session.scalars(
                select(ConversationModel).where(ConversationModel.project_id == project.id)
            ).all()
        )
        # Valores lidos antes da remoção: depois do cascade o objeto sai da sessão.
        project_id = str(project.id)
        name = project.name
        root_path = project.root_path
        removed = delete_cascade(self._session, "projects", project.id)
        self._session.flush()
        return {
            "deleted": True,
            "project_id": project_id,
            "name": name,
            "conversations": len(conversations),
            "root_path": root_path,
            "rows": removed,
        }

    def get_project(self, project_id: uuid.UUID) -> ProjectModel:
        """Projeto por identificador.

        Args:
            project_id: identificador do projeto.

        Returns:
            O projeto encontrado.

        Raises:
            LookupError: quando o projeto não existe.
        """
        project = self._session.get(ProjectModel, project_id)
        if project is None:
            raise LookupError(f"Projeto não encontrado: {project_id}")
        return project

    def add_memory(self, project_id: uuid.UUID, data: MemoryCreate) -> MemoryRecordModel:
        """Grava um registro de memória do projeto, já estruturado.

        Args:
            project_id: identificador do projeto.
            data: dados da memória.

        Returns:
            O registro gravado, com resumo e outline calculados.

        Raises:
            LookupError: quando o projeto ou a conversa informados não existem.
        """
        self.get_project(project_id)
        if data.conversation_id is not None:
            conversation = self._session.get(ConversationModel, data.conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise LookupError("Conversa inválida para este projeto")
        outline = structure_memory(data.content)
        branch_id = data.branch_id
        if branch_id is None and data.conversation_id is not None:
            conversation = self._session.get(ConversationModel, data.conversation_id)
            if conversation is not None:
                branch_id = conversation.active_branch_id
        record = MemoryRecordModel(
            project_id=project_id,
            conversation_id=data.conversation_id,
            branch_id=branch_id,
            task_id=data.task_id,
            kind=data.kind.value,
            title=data.title,
            content=data.content,
            summary=outline["summary"],
            outline_json=outline,
            source_refs_json=data.source_refs,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_memory(self, project_id: uuid.UUID, kind: MemoryKind | None = None) -> list[MemoryRecordModel]:
        """Registros de memória de um projeto, do mais recente ao mais antigo.

        Args:
            project_id: identificador do projeto.
            kind: tipo de memória a filtrar, quando informado.

        Returns:
            A lista de registros de memória.

        Raises:
            LookupError: quando o projeto não existe.
        """
        self.get_project(project_id)
        stmt = select(MemoryRecordModel).where(MemoryRecordModel.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(MemoryRecordModel.kind == kind.value)
        stmt = stmt.order_by(MemoryRecordModel.created_at.desc())
        return list(self._session.scalars(stmt).all())
