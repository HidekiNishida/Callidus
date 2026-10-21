"""
Arquivo: src/agent/context/operation_builder.py
Nome: operation_builder.py
Propósito: montar o contexto de uma operação do agente a partir do banco, do grafo e do projeto.
Responsabilidade: camada de aplicação — coleta dos componentes do prompt e gravação do snapshot do contexto.
Componentes: OperationContextBuilder, GLOBAL_RULES, FILE_CHARS, FILES_TOTAL.
Dependências: agent.context.assembler, agent.context.budget, agent.knowledge, agent.memory.store, agent.services.contract_service, agent.security.paths, agent.skills, agent.tools.builtins, agent.persistence.models.
Observações: o contexto montado é persistido como snapshot; estouro de orçamento gera snapshot e erro.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from agent.context.assembler import build_operation_context
from agent.context.budget import BudgetResult, ContextBudgetError, group_categories
from agent.domain.failures import describe_failures
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.knowledge.indexer import grep_symbols_in_objective
from agent.orchestrator.approach import render_approach
from agent.persistence.models import ContextSnapshotModel, MemoryRecordModel, TaskDependencyModel, TaskModel
from agent.services.contract_service import ContractService
from agent.providers.base import ModelProfile
from agent.security.paths import PathSecurityError, resolve_under_root
from agent.guides.discover import guide_digest
from agent.memory.operational import child_summary, remember_artifact, render_for_prompt
from agent.memory.store import choose_memory_index, fragments_for_prompt, structure_memory
from agent.persistence.models import BranchModel
from agent.services.branches import memory_visible
from agent.orchestrator.strategy import ProfessionalStrategy
from agent.skills import SkillMatch, SkillSelector, get_skill_registry
from agent.tools.builtins import TOOL_CATALOG
from sqlalchemy import select


FILE_CHARS = 8000
FILES_TOTAL = 12000
_PATH_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z0-9]{1,6})(?![\w/-])")


GLOBAL_RULES = (
    "Responda de forma concisa. Use ferramentas apenas quando autorizado. "
    "Não invente arquivos ou testes executados."
)


class OperationContextBuilder:
    """Monta o contexto de cada operação do agente a partir do estado persistido.

    Atributos:
        _session: sessão de leitura e escrita usada para consultar e gravar o snapshot.
        _kg: serviço do grafo de conhecimento, consultado para trechos técnicos.
    """

    def __init__(self, session: Session, settings: Any = None) -> None:
        """Cria o construtor de contexto ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas e na gravação do snapshot.
            settings: configurações do processo, usadas para filtrar as capacidades expostas.
        """
        self._session = session
        self._kg = KnowledgeGraphService(session)
        self._settings_obj = settings

    def build_for_task(
        self,
        *,
        project_id: uuid.UUID,
        root_path: str,
        task: TaskModel,
        profile: ModelProfile,
        run_id: uuid.UUID | None = None,
        compact: bool = False,
    ) -> tuple[BudgetResult, ContextSnapshotModel]:
        """Monta o contexto da operação e grava o snapshot. Se o obrigatório não couber, grava um snapshot
        do estouro (custo por componente) e relança `ContextBudgetError` com `snapshot_id`."""
        pressure = (task.metadata_json or {}).get("context_pressure") == "reduce"
        project_rules, memory_note = self._memory_block(project_id, task, tight=pressure)
        operational = render_for_prompt(self._session, task)
        technical = self._technical_snippet(project_id, task.objective)
        contract, contract_paths = self._contract_block(task)
        target_files, included = self._target_files(root_path, task, contract_paths)
        global_objective = self._global_objective(task)
        dependency_results = self._dependency_results(task)
        guides = guide_digest(root_path, task.objective)
        if guides:
            technical = f"{technical}\n\n## Guias do repositório\n{guides}".strip()
        attached = self._attachment_snippet(root_path, task)
        if attached:
            technical = f"{technical}\n\n{attached}".strip()
        acceptance = task.acceptance_criteria or "Atender o objetivo sem violar requisitos canônicos."
        tools_summary = TOOL_CATALOG
        capability = self._capability_summary(root_path, task)
        if capability:
            tools_summary = f"{tools_summary}\n{capability}"
        page = (task.metadata_json or {}).get("prompt_key") == "page"
        read_only = bool((task.metadata_json or {}).get("read_only"))
        if read_only:
            output_format = (
                "Esta etapa é SOMENTE LEITURA: inspecione o projeto com as ferramentas de leitura "
                "e reporte o que encontrou. Não altere nenhum arquivo — a escrita é recusada. "
                "Responda em texto, direto, dizendo o que observou."
            )
        else:
            output_format = (
                'Grave a página inteira: {"path":"index.html","content":"..."}. '
                "O content é o HTML completo, com cabeçalho, seções, estilo e chamado para ação. "
                "Não entregue um esboço de um parágrafo. Responda só JSON."
                if page
                else (
                    "Inspecione o projeto com as ferramentas e faça a alteração com write_file ou edit_file. "
                    f"Você pode pedir no máximo {self._inspection_budget()} leituras; depois disso, faça a alteração. "
                    'Se preferir responder em JSON: criar {"path":"...","content":"..."}, '
                    'editar {"path":"...","old_string":"...","new_string":"..."}. '
                    "Responda só JSON, sem explicação."
                    if (task.metadata_json or {}).get("model_operation")
                    else "JSON estruturado quando solicitado."
                )
            )
        rules = GLOBAL_RULES if not page else f"{GLOBAL_RULES} O arquivo pedido é o produto completo."
        skills_rendered, matched_skills = self._skills_block(root_path, task, profile)
        previous_failures = self._failures_block(task)
        previous_inspection = self._inspection_block(task)
        requirements = self._requirements_block(task)

        try:
            budget = build_operation_context(
                profile,
                global_rules=rules,
                project_rules=project_rules,
                objective=task.objective,
                technical=technical,
                acceptance=acceptance,
                tools_summary=tools_summary,
                output_format=output_format,
                previous_failures=previous_failures,
                previous_inspection=previous_inspection,
                contract=contract,
                target_files=target_files,
                global_objective=global_objective,
                dependency_results=dependency_results,
                skills=skills_rendered,
                requirements=requirements,
                operational=operational,
                compact=compact or pressure,
                pressure=pressure,
            )
        except ContextBudgetError as exc:
            overflow = ContextSnapshotModel(
                project_id=project_id,
                task_id=task.id,
                run_id=run_id,
                estimated_tokens=exc.required_tokens,
                components_json=exc.breakdown,
                strategy_notes_json=[
                    f"estouro: {exc.required_tokens} tokens obrigatórios > orçamento {exc.budget}",
                    "compactado" if compact else "completo",
                ],
                refs_json=[item["name"] for item in exc.breakdown if not item["required"]],
            )
            self._session.add(overflow)
            self._session.flush()
            exc.snapshot_id = str(overflow.id)
            raise
        if matched_skills:
            budget.strategy_notes.append("skills: " + ", ".join(m.skill_id for m in matched_skills))
        if memory_note:
            budget.strategy_notes.append(memory_note)
        if included:
            budget.strategy_notes.append("arquivos: " + ", ".join(included))
        components = [{"role": m.role, "chars": len(m.content)} for m in budget.messages]

        snap = ContextSnapshotModel(
            project_id=project_id,
            task_id=task.id,
            run_id=run_id,
            estimated_tokens=budget.estimated_tokens,
            components_json=components,
            strategy_notes_json=budget.strategy_notes,
            refs_json=budget.dropped,
            categories_json=group_categories(budget.selected),
        )
        self._session.add(snap)
        self._session.flush()
        if budget.dropped or pressure:
            remember_artifact(
                self._session,
                task,
                title="Snapshot de contexto",
                ref=f"snapshot:{snap.id}",
                summary="Componentes fora do prompt: " + (", ".join(budget.dropped) or "nenhum"),
            )
        images = self._image_payloads(root_path, task, profile)
        if images and budget.messages:
            budget.messages[-1].images = images
        return budget, snap

    def _requirements_block(self, task: TaskModel) -> str:
        """Requisitos obrigatórios que esta etapa responde, com o critério de cada um.

        Sem este bloco o modelo executava a etapa sem saber o que tinha de provar: o critério de
        aceite canônico não chegava ao prompt, e a etapa podia "concluir" sem atender ao requisito
        que a validação depois apontava como não comprovado.
        """
        from agent.orchestrator.requirements import (
            MANDATORY,
            effective_covers,
            ensure_requirements,
            root_of,
        )

        try:
            root = root_of(self._session, task)
            reqs = ensure_requirements(self._session, root)
        except Exception:  # pragma: no cover - contrato ausente não impede a execução
            reqs = []
        lines: list[str] = []
        if reqs:
            covers = {c["req"]: c for c in effective_covers(self._session, task, reqs)}
            for req in reqs:
                cover = covers.get(req["id"])
                if cover is None or req["applicability"] != MANDATORY:
                    continue
                part = f" (parte: {cover['part']})" if cover.get("part") else ""
                lines.append(f"- {req['id']}: {req['description']}{part}")
                criterion = str(req.get("criterion") or "").strip()
                if criterion:
                    lines.append(f"  critério de aceite: {criterion}")
        body = ""
        if lines:
            body = (
                "Requisitos obrigatórios que esta etapa tem de atender (todos):\n"
                + "\n".join(lines)
                + "\nA etapa só vale se o requisito for cumprido e comprovado."
            )
        try:
            from agent.orchestrator.quality_contract import render_quality_for_prompt

            quality = render_quality_for_prompt(task.metadata_json)
        except Exception:
            quality = ""
        if quality:
            body = f"{body}\n\n{quality}".strip()
        try:
            from agent.orchestrator.language_strategy import render_operational_for_prompt

            language = render_operational_for_prompt(task.metadata_json)
        except Exception:
            language = ""
        if language:
            body = f"{body}\n\n{language}".strip()
        return body

    def _capability_summary(self, root_path: str, task: TaskModel) -> str:
        """Resumo das capacidades extras expostas nesta etapa.

        O prompt carrega uma linha por família — o detalhe de cada ferramenta vem sob
        demanda, por `tool_catalog` e `tool_help`.

        Args:
            root_path: pasta de trabalho da etapa.
            task: tarefa em foco.

        Returns:
            O resumo em texto; string vazia quando nenhuma família extra se aplica.
        """
        from agent.tools.catalog import capability_summary, exposed_tools
        from agent.tools.registry import get_default_registry

        registry = get_default_registry()
        tool_ids = exposed_tools(
            registry,
            objective=task.objective or "",
            base=(),
            settings=self._settings(),
        )
        return capability_summary(registry, tool_ids)

    def _settings(self) -> Any:
        """Configuração do processo, quando disponível.

        Returns:
            As configurações, ou `None` quando o construtor não as recebeu.
        """
        return self._settings_obj

    def _skills_block(
        self,
        root_path: str,
        task: TaskModel,
        profile: ModelProfile,
    ) -> tuple[str, list[SkillMatch]]:
        """Seleciona as Skills relevantes e as renderiza dentro do orçamento do modelo.

        A estratégia profissional da tarefa (quando existe) define a especialidade líder;
        sem estratégia, a seleção parte das palavras-chave do objetivo. O bloco é limitado
        por uma fração do orçamento de entrada para nunca estourar a janela do modelo.
        """
        selector = SkillSelector(get_skill_registry(root_path))
        task_kind = task.kind.value if hasattr(task.kind, "value") else str(task.kind)
        strategy = ProfessionalStrategy.from_dict((task.metadata_json or {}).get("professional_strategy"))
        if strategy is not None:
            matches = selector.select_for_strategy(strategy, task_kind=task_kind, max_skills=self._max_skills())
        else:
            matches = selector.select(task.objective, task_kind=task_kind, max_skills=self._max_skills())
        # O bloco de skills nunca pode passar de ~12% do orçamento de entrada.
        max_chars = max(400, min(2500, int(profile.input_budget * 0.12)))
        return selector.render_selected_skills(matches, max_chars=max_chars), matches

    def _max_skills(self) -> int:
        """Quantas skills podem entrar no prompt de uma operação.

        Returns:
            O limite configurado; em caso de falha de configuração, o padrão de duas skills.
        """
        try:
            from agent.config import get_settings

            return max(1, int(get_settings().skills_max_per_operation))
        except Exception:  # pragma: no cover - configuração ausente não impede a execução
            return 2

    def _inspection_budget(self) -> int:
        """Quantas leituras o modelo pode fazer antes de responder (o mesmo limite do ciclo)."""
        try:
            from agent.config import get_settings

            return max(1, int(get_settings().max_tool_iterations))
        except Exception:  # pragma: no cover - configuração ausente não impede a execução
            return 6

    def _inspection_block(self, task: TaskModel) -> str:
        """O que a tentativa anterior já leu: evita reler os mesmos arquivos do zero."""
        items = (task.metadata_json or {}).get("inspection") or []
        if not items:
            return ""
        lines = ["Você já inspecionou estes arquivos nesta etapa (use o conteúdo abaixo em vez de ler de novo):"]
        for item in items[:6]:
            path = item.get("path")
            if not path:
                continue
            content = str(item.get("content") or "").strip()
            lines.append(f"- {path}: {content[:600]}" if content else f"- {path}")
        return "\n".join(lines)

    def _failures_block(self, task: TaskModel) -> str:
        """Falhas anteriores + a memória de abordagem + a orientação de recuperação.

        A memória de abordagem vem junto porque é ela que diz **o que precisa ser diferente**
        agora: sem ela, o modelo recebe a lista do que já falhou e repete a mesma operação.
        """
        meta = task.metadata_json or {}
        base = describe_failures(meta.get("failures") or [])
        approach = render_approach(task)
        guidance = str(meta.get("recovery_guidance") or "")
        blocks = [block for block in (base, approach) if block]
        if guidance:
            blocks.append(f"## Orientação de recuperação\n{guidance}")
        return "\n\n".join(blocks)

    def _memory_block(self, project_id: uuid.UUID, task: TaskModel, *, tight: bool = False) -> tuple[str, str]:
        """Monta o bloco de memória (canônica e contextual) que entra no prompt da operação.

        Args:
            project_id: projeto dono das memórias.
            task: tarefa em execução.
            tight: quando verdadeiro, cada fragmento fica mais curto porque o orçamento apertou.
        """
        index = self._memory_index(project_id, task)
        chosen = choose_memory_index(index, task.objective)
        note = f"memória: índice {len(index)}, escolhidas {len(chosen)}"
        if not chosen:
            return "(sem memória registrada)", note
        bodies = self._memory_bodies([item["id"] for item in chosen])
        fragment_budget = 200 if tight else 480
        lines: list[str] = []
        for item in chosen:
            fragment = fragments_for_prompt(
                item.get("summary") or "",
                bodies.get(item["id"], ""),
                task.objective,
                budget=fragment_budget,
            )
            if not fragment:
                continue
            label = "projeto" if item["scope"] == "project" else "conversa"
            lines.append(f"- ({label}/{item['kind']}) {item['title']}: {fragment}")
        if not lines:
            return "(sem memória registrada)", note
        return "\n".join(lines), note

    def _memory_index(self, project_id: uuid.UUID, task) -> list[dict]:
        """Índice de memórias visíveis para a tarefa, com resumo, fatos e tópicos.

        Args:
            project_id: projeto dono das memórias.
            task: tarefa em execução, usada para filtrar conversa e ramo.

        Returns:
            A lista de memórias visíveis, mais recentes primeiro.
        """
        conversation_id = task.conversation_id
        stmt = (
            select(
                MemoryRecordModel.id,
                MemoryRecordModel.title,
                MemoryRecordModel.summary,
                MemoryRecordModel.outline_json,
                MemoryRecordModel.kind,
                MemoryRecordModel.conversation_id,
                MemoryRecordModel.branch_id,
                MemoryRecordModel.created_at,
            )
            .where(MemoryRecordModel.project_id == project_id)
            .where(
                (MemoryRecordModel.conversation_id.is_(None))
                | (MemoryRecordModel.conversation_id == conversation_id)
            )
            .order_by(MemoryRecordModel.created_at.desc())
            .limit(24)
        )
        catalog: dict = {}
        if task.conversation_id and task.branch_id:
            catalog = {
                item.id: item
                for item in self._session.scalars(
                    select(BranchModel).where(BranchModel.conversation_id == task.conversation_id)
                ).all()
            }
        rows: list[dict] = []
        for record in self._session.execute(stmt):
            if not memory_visible(
                memory_branch_id=record.branch_id,
                memory_created_at=record.created_at,
                conversation_id=record.conversation_id,
                task_branch_id=task.branch_id,
                branches=catalog,
            ):
                continue
            outline = record.outline_json or structure_memory(record.summary or record.title or "")
            rows.append(
                {
                    "id": record.id,
                    "title": record.title,
                    "summary": outline.get("summary") or record.summary or "",
                    "facts": outline.get("facts") or [],
                    "topics": outline.get("topics") or [],
                    "kind": record.kind,
                    "scope": "project" if record.conversation_id is None else "conversation",
                }
            )
        return rows

    def _memory_bodies(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Conteúdo completo das memórias selecionadas.

        Args:
            ids: identificadores das memórias escolhidas.

        Returns:
            Um dicionário de identificador para conteúdo.
        """
        if not ids:
            return {}
        stmt = select(MemoryRecordModel.id, MemoryRecordModel.content).where(MemoryRecordModel.id.in_(ids))
        return {row.id: row.content or "" for row in self._session.execute(stmt)}

    def _technical_snippet(self, project_id: uuid.UUID, objective: str) -> str:
        """Trechos técnicos sugeridos pelo grafo de conhecimento a partir do objetivo.

        Args:
            project_id: projeto em que a busca acontece.
            objective: texto da etapa, do qual são extraídos os símbolos.

        Returns:
            A lista de referências encontradas, ou uma dica para inspecionar manualmente.
        """
        parts: list[str] = []
        for token in grep_symbols_in_objective(objective)[:8]:
            hits = self._kg.search(project_id, token, limit=3)
            for h in hits:
                parts.append(f"[{h['kind']}] {h['ref']}")
        return "\n".join(parts) if parts else "(nenhum trecho automático; use list_dir ou search_grep)"

    def _contract_block(self, task: TaskModel) -> tuple[str, list[str]]:
        """Contrato da tarefa (entradas, saídas, invariantes e aceite) e os arquivos nele referenciados.

        Args:
            task: tarefa em execução.

        Returns:
            O contrato em texto e a lista de caminhos citados nele.
        """
        service = ContractService(self._session)
        row = service.get(task.id)
        if row is None:
            return "", []
        parts = {
            "entradas": row.inputs_json,
            "saídas": row.outputs_json,
            "invariantes": row.invariants_json,
            "aceite": row.acceptance_json,
        }
        body = "\n".join(
            f"{label}: {json.dumps(value, ensure_ascii=False)[:600]}" for label, value in parts.items() if value
        )
        return body, service.file_refs_from_contract(row)

    def _target_files(self, root_path: str, task: TaskModel, extra: list[str]) -> tuple[str, list[str]]:
        """Arquivos citados no pedido (título, objetivo, critérios, contrato, path da ferramenta) que existem
        no projeto, com o conteúdo atual. Arquivo grande entra com o início e o aviso do tamanho."""
        meta = task.metadata_json or {}
        tool_path = (meta.get("tool_args") or {}).get("path")
        candidates = [*extra, *([tool_path] if isinstance(tool_path, str) else [])]
        for text in (task.title, task.objective, task.acceptance_criteria or ""):
            candidates.extend(_PATH_TOKEN.findall(text or ""))
        blocks: list[str] = []
        included: list[str] = []
        used = 0
        for rel in dict.fromkeys(c.strip().strip("`'\"") for c in candidates if c):
            try:
                full = resolve_under_root(root_path, rel)
            except PathSecurityError:
                continue
            if not full.is_file() or full.stat().st_size > 2_000_000:
                continue
            raw = full.read_bytes()
            if b"\0" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="replace")
            room = min(FILE_CHARS, FILES_TOTAL - used)
            if room <= 0:
                break
            if len(text) > room:
                lines = text.count("\n") + 1
                body = text[:room] + f"\n… (arquivo com {len(text)} caracteres e {lines} linhas; leia o resto se precisar)"
            else:
                body = text
            blocks.append(f"--- {rel} ---\n{body}")
            included.append(rel)
            used += min(len(text), room)
        return "\n\n".join(blocks), included

    def _global_objective(self, task: TaskModel) -> str:
        """Objetivo da raiz da decomposição: o porquê da etapa dentro do pedido original.

        Args:
            task: tarefa em execução.

        Returns:
            O objetivo da raiz, ou string vazia quando a tarefa já é a raiz.
        """
        current, seen = task, set()
        while current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            parent = self._session.get(TaskModel, current.parent_id)
            if parent is None:
                break
            current = parent
        if current.id == task.id or (current.objective or "").strip() == (task.objective or "").strip():
            return ""
        return (current.objective or current.title)[:800]

    def _dependency_results(self, task: TaskModel) -> str:
        """O que as etapas das quais esta depende produziram (resumo curto de cada uma)."""
        dep_ids = list(
            self._session.scalars(
                select(TaskDependencyModel.depends_on_task_id).where(TaskDependencyModel.task_id == task.id)
            )
        )
        lines: list[str] = []
        for dep_id in dep_ids:
            dep = self._session.get(TaskModel, dep_id)
            if dep is None:
                continue
            lines.append(child_summary(self._session, dep))
        return "\n".join(lines)

    def _ancestor_attachments(self, task: TaskModel) -> list[dict]:
        """Anexos do pedido, somando os das tarefas ancestrais.

        Args:
            task: tarefa em execução.

        Returns:
            A lista de referências de anexo, da tarefa mais antiga para a atual.
        """
        current: TaskModel | None = task
        seen: set[uuid.UUID] = set()
        found: list[dict] = []
        while current is not None and current.id not in seen:
            seen.add(current.id)
            found.extend((current.metadata_json or {}).get("attachments") or [])
            if current.parent_id is None:
                break
            current = self._session.get(TaskModel, current.parent_id)
        return found

    def _attachment_snippet(self, root_path: str, task: TaskModel) -> str:
        """Trecho dos anexos textuais do pedido, para o modelo não precisar reler tudo.

        Args:
            root_path: raiz do projeto, usada para resolver os caminhos com segurança.
            task: tarefa em execução.

        Returns:
            O bloco de anexos em texto, ou string vazia quando não há anexos textuais.
        """
        refs = self._ancestor_attachments(task)
        if not refs:
            return ""
        lines = ["Anexos do pedido (leia o arquivo se o trecho abaixo não bastar):"]
        for ref in refs[:8]:
            path = str(ref.get("path") or "")
            lines.append(f"- {ref.get('kind')} {ref.get('name')} ({path})")
            if ref.get("kind") != "text" or not path:
                continue
            try:
                full = resolve_under_root(root_path, path)
                text = full.read_text(encoding="utf-8", errors="replace")
            except (OSError, PathSecurityError):
                continue
            preview = text[:2000]
            if len(text) > 2000:
                preview += "\n…"
            lines.append(f"--- {ref.get('name')} ---\n{preview}")
        return "\n".join(lines)

    def _image_payloads(self, root_path: str, task: TaskModel, profile: ModelProfile) -> list[str]:
        """Anexos de imagem codificados em base64, quando o modelo aceita visão.

        Args:
            root_path: raiz do projeto, usada para resolver os caminhos com segurança.
            task: tarefa em execução.
            profile: perfil do modelo, consultado para a capacidade de visão.

        Returns:
            A lista de imagens codificadas; no máximo duas, e nenhuma acima de 4 MB.
        """
        if not profile.supports_vision:
            return []
        payloads: list[str] = []
        for ref in self._ancestor_attachments(task):
            if ref.get("kind") != "image" or not ref.get("path"):
                continue
            try:
                raw = resolve_under_root(root_path, str(ref["path"])).read_bytes()
            except (OSError, PathSecurityError):
                continue
            if len(raw) > 4_000_000:
                continue
            payloads.append(base64.b64encode(raw).decode("ascii"))
            if len(payloads) >= 2:
                break
        return payloads
