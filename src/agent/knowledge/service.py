"""
Arquivo: src/agent/knowledge/service.py
Nome: service.py
Propósito: orquestrar o ciclo completo de aquisição, processamento e armazenamento de conhecimento.
Responsabilidade: camada de aplicação — coordenar discovery, request, acquisition, processing, memory.
Componentes: KnowledgeEngineService.
Dependências: agent.knowledge.models, agent.knowledge.request, agent.knowledge.providers, agent.persistence.models, sqlalchemy, uuid.
Observações: independente de modelo de inferência; integra com ProjectService e RunOrchestrator.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.knowledge.models import (
    KnowledgeItemModel,
    KnowledgeSourceModel,
    KnowledgeRequestModel,
    KnowledgeValidationModel,
    KnowledgeValidationStatus,
    KnowledgeKind,
    KnowledgeSourceKind,
)
from agent.knowledge.request import KnowledgeDiscovery, KnowledgeRequestCreate, KnowledgeDepth
from agent.knowledge.providers import DuckDuckGoProvider, GitHubProvider, DocumentationProvider
from agent.persistence.models import (
    ProjectModel, TaskModel, AgentModel,
    KnowledgeUsageModel, KnowledgeVersionModel,
)


class KnowledgeEngineService:
    """
    Orquestrador central do Knowledge Engine.

    Responsabilidades:
    1. Receber solicitações de conhecimento (de tasks, agents, ou manual)
    2. Verificar memória existente (knowledge_items)
    3. Identificar se já existe conhecimento suficiente
    4. Selecionar fontes apropriadas (search providers, browser, etc.)
    5. Distribuir consultas aos adaptadores
    6. Reunir e normalizar resultados
    7. Comparar fontes, sintetizar, validar
    8. Persistir descobertas (knowledge_items + sources + validations)
    9. Retornar síntese ao solicitante
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._discovery = KnowledgeDiscovery()

    # ==================== CONSULTA E RECUPERAÇÃO ====================

    def search_knowledge(
        self,
        project_id: uuid.UUID,
        query: str,
        *,
        kind: str | None = None,
        technology: str | None = None,
        version: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[KnowledgeItemModel]:
        """Busca itens de conhecimento relevantes."""
        stmt = select(KnowledgeItemModel).where(KnowledgeItemModel.project_id == project_id)

        if kind:
            stmt = stmt.where(KnowledgeItemModel.kind == kind)
        if technology:
            stmt = stmt.where(KnowledgeItemModel.technology == technology)
        if version:
            stmt = stmt.where(KnowledgeItemModel.version == version)
        if min_confidence > 0:
            stmt = stmt.where(KnowledgeItemModel.confidence >= min_confidence)

        stmt = stmt.where(KnowledgeItemModel.validation_status != KnowledgeValidationStatus.FAILED.value)
        stmt = stmt.order_by(KnowledgeItemModel.confidence.desc(), KnowledgeItemModel.updated_at.desc()).limit(limit)

        return list(self._session.scalars(stmt).all())

    def get_knowledge_item(self, item_id: uuid.UUID) -> KnowledgeItemModel | None:
        """Recupera um item de conhecimento por ID."""
        return self._session.get(KnowledgeItemModel, item_id)

    def get_knowledge_with_sources(self, item_id: uuid.UUID) -> dict | None:
        """Recupera item com suas fontes e validações."""
        item = self.get_knowledge_item(item_id)
        if not item:
            return None

        sources = list(
            self._session.scalars(
                select(KnowledgeSourceModel).where(KnowledgeSourceModel.item_id == item_id)
            ).all()
        )
        validations = list(
            self._session.scalars(
                select(KnowledgeValidationModel).where(KnowledgeValidationModel.item_id == item_id)
            ).all()
        )

        return {
            "item": item,
            "sources": sources,
            "validations": validations,
        }

    # ==================== DESCOBERTA DE LACUNAS ====================

    def evaluate_knowledge_need(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID | None,
        agent_id: uuid.UUID | None,
        model_confidence: float | None,
        context_has_answer: bool,
        repeated_failures: int,
        requires_updated_info: bool,
        needs_specialized_docs: bool,
        complexity_score: float,
        objective: str,
    ) -> KnowledgeRequestCreate | None:
        """
        Avalia a necessidade de conhecimento e cria solicitação se necessário.

        Integração sugerida: chamar no RunOrchestrator antes de executar task RUNNING,
        ou no ContextAssembler ao montar contexto.
        """
        # Buscar conhecimento existente relevante
        existing = self.search_knowledge(project_id, query=objective, limit=10)
        existing_dicts = [
            {
                "id": str(k.id),
                "title": k.title,
                "content": k.content,
                "tags": k.context_tags_json or [],
                "confidence": k.confidence,
            }
            for k in existing
        ]

        should_acquire, gap = self._discovery.should_acquire(
            model_confidence=model_confidence,
            context_has_answer=context_has_answer,
            repeated_failures=repeated_failures,
            requires_updated_info=requires_updated_info,
            needs_specialized_docs=needs_specialized_docs,
            complexity_score=complexity_score,
            available_knowledge=existing_dicts,
        )

        if not should_acquire or not gap:
            return None

        return self._discovery.create_request_from_gap(gap, project_id, task_id, agent_id)

    # ==================== SOLICITAÇÕES ====================

    def create_request(self, data: KnowledgeRequestCreate) -> KnowledgeRequestModel:
        """Cria uma nova solicitação de conhecimento."""
        request = KnowledgeRequestModel(
            project_id=data.project_id,
            task_id=data.task_id,
            agent_id=data.agent_id,
            question=data.question,
            context_json=data.context,
            constraints_json=data.constraints,
            desired_kind=data.desired_kind,
            depth=data.depth.value,
            validation_criteria_json=data.validation_criteria,
            max_acquisition_time_sec=data.max_acquisition_time_sec,
            status="pending",
        )
        self._session.add(request)
        self._session.flush()
        return request

    def update_request_status(
        self,
        request_id: uuid.UUID,
        status: str,
        *,
        result_item_id: uuid.UUID | None = None,
        error_message: str | None = None,
    ) -> KnowledgeRequestModel | None:
        """Atualiza status de uma solicitação."""
        request = self._session.get(KnowledgeRequestModel, request_id)
        if not request:
            return None

        request.status = status
        request.updated_at = datetime.now(UTC)

        if status == "in_progress" and not request.started_at:
            request.started_at = datetime.now(UTC)
        elif status in {"completed", "failed", "partial", "cancelled"}:
            request.completed_at = datetime.now(UTC)
            if result_item_id:
                request.result_item_id = result_item_id
            if error_message:
                request.error_message = error_message

        self._session.flush()
        return request

    # ==================== ARMAZENAMENTO DE CONHECIMENTO ====================

    def save_knowledge(
        self,
        *,
        project_id: uuid.UUID,
        kind: str,
        title: str,
        content: str,
        summary: str | None = None,
        technology: str | None = None,
        version: str | None = None,
        context_tags: list[str] | None = None,
        confidence: float = 0.5,
        sources: list[dict] | None = None,
        validation_status: str = KnowledgeValidationStatus.UNVALIDATED.value,
    ) -> KnowledgeItemModel:
        """Salva um novo item de conhecimento com suas fontes."""
        item = KnowledgeItemModel(
            project_id=project_id,
            kind=kind,
            title=title,
            content=content,
            summary=summary,
            technology=technology,
            version=version,
            context_tags_json=context_tags,
            confidence=confidence,
            validation_status=validation_status,
            source_count=len(sources) if sources else 0,
        )
        self._session.add(item)
        self._session.flush()

        # Salvar fontes
        if sources:
            for src in sources:
                source = KnowledgeSourceModel(
                    item_id=item.id,
                    source_kind=src.get("source_kind", KnowledgeSourceKind.WEB_SEARCH.value),
                    title=src.get("title"),
                    url=src.get("url"),
                    author=src.get("author"),
                    published_at=src.get("published_at"),
                    credibility=src.get("credibility", 0.5),
                    raw_content=src.get("raw_content"),
                    extracted_content=src.get("extracted_content"),
                    meta_json=src.get("meta"),
                )
                self._session.add(source)

        self._session.flush()
        return item

    def update_knowledge(
        self,
        item_id: uuid.UUID,
        *,
        title: str | None = None,
        content: str | None = None,
        summary: str | None = None,
        confidence: float | None = None,
        validation_status: str | None = None,
        change_reason: str | None = None,
        changed_by: str | None = None,
    ) -> KnowledgeItemModel | None:
        """Atualiza um item de conhecimento, criando versão histórica."""
        item = self.get_knowledge_item(item_id)
        if not item:
            return None

        # Criar versão histórica antes de alterar
        version = KnowledgeVersionModel(
            item_id=item.id,
            version_number=len(
                self._session.scalars(
                    select(KnowledgeVersionModel).where(KnowledgeVersionModel.item_id == item_id)
                ).all()
            )
            + 1,
            title=item.title,
            content=item.content,
            summary=item.summary,
            change_reason=change_reason,
            changed_by=changed_by,
        )
        self._session.add(version)

        # Atualizar item
        if title is not None:
            item.title = title
        if content is not None:
            item.content = content
        if summary is not None:
            item.summary = summary
        if confidence is not None:
            item.confidence = confidence
        if validation_status is not None:
            item.validation_status = validation_status

        item.updated_at = datetime.now(UTC)
        self._session.flush()
        return item

    # ==================== VALIDAÇÃO ====================

    def add_validation(
        self,
        item_id: uuid.UUID,
        validation_kind: str,
        *,
        method: str | None = None,
        criteria: dict | None = None,
        evidence: dict | None = None,
        passed: bool | None = None,
        notes: str | None = None,
        validated_by: str | None = None,
    ) -> KnowledgeValidationModel | None:
        """Adiciona uma validação a um item de conhecimento."""
        item = self.get_knowledge_item(item_id)
        if not item:
            return None

        validation = KnowledgeValidationModel(
            item_id=item_id,
            validation_kind=validation_kind,
            method=method,
            criteria_json=criteria,
            evidence_json=evidence,
            passed=passed,
            notes=notes,
            validated_at=datetime.now(UTC) if passed is not None else None,
            validated_by=validated_by,
            status=(
                KnowledgeValidationStatus.VALIDATED.value
                if passed
                else KnowledgeValidationStatus.FAILED.value if passed is False else KnowledgeValidationStatus.UNVALIDATED.value
            ),
        )
        self._session.add(validation)

        # Atualizar status do item baseado na validação
        if passed is True:
            item.validation_status = KnowledgeValidationStatus.VALIDATED.value
        elif passed is False:
            item.validation_status = KnowledgeValidationStatus.FAILED.value

        self._session.flush()
        return validation

    # ==================== USO E FEEDBACK ====================

    def record_usage(
        self,
        item_id: uuid.UUID,
        *,
        task_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        context: str | None = None,
        outcome: str,
        success: bool | None = None,
        evidence_ref: str | None = None,
    ) -> None:
        """Registra uso de um item de conhecimento."""
        item = self.get_knowledge_item(item_id)
        if not item:
            return

        usage = KnowledgeUsageModel(
            item_id=item_id,
            task_id=task_id,
            run_id=run_id,
            agent_id=agent_id,
            context=context,
            outcome=outcome,
            success=success,
            evidence_ref=evidence_ref,
        )
        self._session.add(usage)

        # Atualizar contadores do item
        item.usage_count += 1
        item.last_used_at = datetime.now(UTC)

        # Se falhou, registrar para aprendizado
        if success is False:
            self.add_validation(
                item_id,
                "usage_failure",
                method="task_execution",
                criteria={"outcome": outcome},
                evidence={"evidence_ref": evidence_ref},
                passed=False,
                notes=f"Falha na aplicação: {outcome}",
                validated_by="knowledge_engine",
            )

        self._session.flush()

    # ==================== RELACIONAMENTOS ====================

    def link_knowledge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        strength: float = 1.0,
        notes: str | None = None,
    ) -> None:
        """Cria relação entre dois itens de conhecimento."""
        # Verificar se já existe
        existing = self._session.scalars(
            select(KnowledgeRelationModel).where(
                KnowledgeRelationModel.source_id == source_id,
                KnowledgeRelationModel.target_id == target_id,
                KnowledgeRelationModel.relation_type == relation_type,
            )
        ).first()

        if existing:
            return

        relation = KnowledgeRelationModel(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            strength=strength,
            notes=notes,
        )
        self._session.add(relation)
        self._session.flush()

    # ==================== ESTATÍSTICAS ====================

    def get_stats(self, project_id: uuid.UUID) -> dict:
        """Estatísticas do knowledge engine para um projeto."""
        total_items = self._session.scalar(
            select(KnowledgeItemModel)
            .where(KnowledgeItemModel.project_id == project_id)
            .with_only_columns(KnowledgeItemModel.id)
        )
        # Contagem real
        from sqlalchemy import func
        total = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(KnowledgeItemModel.project_id == project_id)
        ) or 0

        validated = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == KnowledgeValidationStatus.VALIDATED.value,
            )
        ) or 0

        failed = self._session.scalar(
            select(func.count(KnowledgeItemModel.id)).where(
                KnowledgeItemModel.project_id == project_id,
                KnowledgeItemModel.validation_status == KnowledgeValidationStatus.FAILED.value,
            )
        ) or 0

        total_usage = self._session.scalar(
            select(func.sum(KnowledgeItemModel.usage_count)).where(
                KnowledgeItemModel.project_id == project_id
            )
        ) or 0

        by_kind = {}
        for kind in KnowledgeKind:
            count = self._session.scalar(
                select(func.count(KnowledgeItemModel.id)).where(
                    KnowledgeItemModel.project_id == project_id,
                    KnowledgeItemModel.kind == kind.value,
                )
            ) or 0
            by_kind[kind.value] = count

        return {
            "total_items": total,
            "validated": validated,
            "failed": failed,
            "unvalidated": total - validated - failed,
            "total_usage": total_usage,
            "by_kind": by_kind,
        }

    # ==================== AQUISIÇÃO DE CONHECIMENTO ====================

    async def acquire_knowledge(
        self,
        request_id: uuid.UUID,
        *,
        providers: list[str] | None = None,
        max_results_per_provider: int = 5,
    ) -> KnowledgeItemModel | None:
        """
        Adquire conhecimento externo para uma solicitação usando provedores configurados.

        Args:
            request_id: ID da solicitação de conhecimento.
            providers: Lista de provedores a usar ('duckduckgo', 'github', 'documentation').
                      None usa todos disponíveis.
            max_results_per_provider: Máximo de resultados por provedor.

        Returns:
            O item de conhecimento criado, ou None se falhou.
        """
        request = self._session.get(KnowledgeRequestModel, request_id)
        if not request:
            return None

        self.update_request_status(request_id, "in_progress")

        # Selecionar provedores
        available_providers = {
            "duckduckgo": DuckDuckGoProvider(),
            "github": GitHubProvider(),
            "documentation": DocumentationProvider(),
        }
        selected = providers or list(available_providers.keys())
        provider_instances = {k: available_providers[k] for k in selected if k in available_providers}

        if not provider_instances:
            self.update_request_status(request_id, "failed", error_message="Nenhum provedor válido")
            return None

        # Coletar resultados de todos os provedores
        all_sources: list[dict] = []
        query = request.question

        for name, provider in provider_instances.items():
            try:
                results = await provider.search(request.question, limit=max_results_per_provider)
                for r in results:
                    all_sources.append({
                        "source_kind": provider.source_kind,
                        "title": r.title,
                        "url": r.url,
                        "description": r.description,
                        "published_at": r.published_at,
                        "author": r.author,
                        "credibility": r.credibility,
                        "meta": r.meta,
                    })
            except Exception as exc:
                # Log error but continue with other providers
                pass

        if not all_sources:
            self.update_request_status(request_id, "failed", error_message="Nenhum resultado encontrado")
            return None

        # Sintetizar conhecimento a partir das fontes
        # Por enquanto, cria um item por fonte (futuro: síntese comparativa)
        created_items = []
        for src in all_sources:
            # Determinar kind baseado na fonte
            kind_map = {
                "web_search": "documentation",
                "github": "code_example",
                "documentation": "documentation",
            }
            kind = kind_map.get(src.get("source_kind", "web_search"), "documentation")

            # Extrair tecnologia da query se possível
            technology = self._extract_technology(request.question)

            item = self.save_knowledge(
                project_id=request.project_id,
                kind=kind,
                title=src.get("title", f"Knowledge from {src.get('source_kind')}"),
                content=src.get("description") or src.get("title", ""),
                summary=f"Acquired from {src.get('source_kind')}: {src.get('title', '')[:100]}",
                technology=self._extract_technology(request.question),
                confidence=src.get("credibility", 0.5),
                sources=[src],
                validation_status="unvalidated",
            )
            created_items.append(item)

        # Link first item to request
        if created_items:
            main_item = created_items[0]
            self.update_request_status(request.id, "completed", result_item_id=main_item.id)
            return main_item

        self.update_request_status(request_id, "failed", error_message="Falha ao criar item de conhecimento")
        return None

    def _extract_technology(self, text: str) -> str | None:
        """Extrai menção de tecnologia do texto."""
        tech_keywords = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "rust": "rust",
            "go": "go",
            "java": "java",
            "c++": "cpp",
            "c#": "csharp",
            "sql": "sql",
            "docker": "docker",
            "kubernetes": "kubernetes",
            "aws": "aws",
            "gcp": "gcp",
            "azure": "azure",
            "react": "react",
            "vue": "vue",
            "angular": "angular",
            "django": "django",
            "fastapi": "fastapi",
            "flask": "flask",
            "postgresql": "postgresql",
            "mysql": "mysql",
            "redis": "redis",
            "mongodb": "mongodb",
            "elasticsearch": "elasticsearch",
            "kafka": "kafka",
            "rabbitmq": "rabbitmq",
            "graphql": "graphql",
            "rest": "rest",
            "grpc": "grpc",
            "asyncio": "python",
            "async": "python",
            "await": "python",
        }
        text_lower = text.lower()
        for keyword, tech in tech_keywords.items():
            if keyword in text_lower:
                return tech
        return None