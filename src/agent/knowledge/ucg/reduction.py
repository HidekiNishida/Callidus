"""
Arquivo: src/agent/knowledge/ucg/reduction.py
Nome: reduction.py
Propósito: redução progressiva de contexto — seleção explicável e limitada de arquivos e
memórias para a janela do modelo, sem carregar catálogos inteiros.
Responsabilidade: camada de aplicação — usa `InspectionIndex` (hash, relevância, cache) para
classificar o que já foi inspecionado e escolher um conjunto mínimo dentro do orçamento,
registrando por que cada item entrou ou saiu.
Componentes: FileSelection, ContextReduction, ProgressiveContextReducer.
Dependências: agent.memory.inspection, agent.memory.layers, agent.memory.state,
agent.persistence.models, dataclasses, typing.
Observações: não cria mecanismo paralelo de contexto; integra-se ao `InspectionIndex` existente
e ao `TaskStateService`/`MemoryLayers`. Não grava dados; é um cálculo de seleção apenas-leitura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.memory.inspection import FileInspection, InspectionIndex, relevance_score
from agent.memory.layers import MemoryLayers
from agent.memory.state import TaskStateService
from agent.persistence.models import TaskModel


@dataclass
class FileSelection:
    """Resultado da seleção de um arquivo para o contexto.

    Atributos:
        path: caminho relativo ao projeto.
        included: se o arquivo entrou no contexto reduzido.
        reason: motivo legível da inclusão ou exclusão.
        relevance: pontuação de relevância (0 a 100).
        size: tamanho em bytes.
        stale: se o arquivo mudou desde a última inspeção.
    """

    path: str
    included: bool
    reason: str
    relevance: int = 0
    size: int = 0
    stale: bool = False


@dataclass
class ContextReduction:
    """Resultado da redução progressiva de contexto.

    Atributos:
        selected: arquivos incluídos no contexto, por relevância decrescente.
        excluded: arquivos excluídos com motivo.
        total_bytes: soma dos tamanhos dos selecionados.
        estimated_tokens: estimativa de tokens dos selecionados.
        budget_respected: se o orçamento foi respeitado.
        explanation: resumo legível da seleção.
    """

    selected: list[FileSelection] = field(default_factory=list)
    excluded: list[FileSelection] = field(default_factory=list)
    total_bytes: int = 0
    estimated_tokens: int = 0
    budget_respected: bool = True
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "selected": [
                {
                    "path": s.path,
                    "reason": s.reason,
                    "relevance": s.relevance,
                    "size": s.size,
                    "stale": s.stale,
                }
                for s in self.selected
            ],
            "excluded": [
                {
                    "path": s.path,
                    "reason": s.reason,
                    "relevance": s.relevance,
                    "size": s.size,
                    "stale": s.stale,
                }
                for s in self.excluded
            ],
            "total_bytes": self.total_bytes,
            "estimated_tokens": self.estimated_tokens,
            "budget_respected": self.budget_respected,
            "explanation": self.explanation,
        }


#: Estimativa de caracteres por token, alinhada a `agent.providers.base`.
_CHARS_PER_TOKEN = 3


#: Relevância mínima para um arquivo ser candidato à inclusão.
_MIN_RELEVANCE = 10


class ProgressiveContextReducer:
    """Redutor de contexto progressivo e explicável.

    Seleciona apenas os arquivos inspecionados que são relevantes para o objetivo
    e cabem no orçamento, evitando carregar o catálogo de arquivos inteiro.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _state: serviço de estado estruturado da tarefa.
        _memories: recuperação de memória por camada.
    """

    def __init__(self, session: Any) -> None:
        """Cria o redutor ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy usada nas consultas de leitura.
        """
        self._session = session
        self._state = TaskStateService(session)
        self._memories = MemoryLayers(session)

    def reduce(
        self,
        task_id: Any,
        objective: str,
        *,
        root_path: str,
        budget_bytes: int = 12000,
        max_files: int = 12,
    ) -> ContextReduction:
        """Reduz o contexto de uma tarefa aos arquivos mais relevantes dentro do orçamento.

        Args:
            task_id: identificador da tarefa.
            objective: objetivo da etapa, usado para pontuar a relevância.
            root_path: raiz do projeto, para resolver caminhos e detectar stale.
            budget_bytes: orçamento de bytes para os arquivos selecionados.
            max_files: quantidade máxima de arquivos selecionados.

        Returns:
            O `ContextReduction` com selecionados, excluídos e justificativas.
        """
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return ContextReduction(
                explanation="tarefa não encontrada; contexto reduzido vazio",
            )

        index = InspectionIndex.from_metadata(task.metadata_json or {})
        inspections = index.items()

        # Monta seleções candidatas com motivo de inclusão/exclusão.
        candidates: list[FileSelection] = []
        for insp in inspections:
            stale = _is_stale(insp, root_path)
            relevance = insp.relevance or relevance_score(objective, insp.summary, insp.snippets)
            if stale:
                candidates.append(
                    FileSelection(
                        path=insp.path,
                        included=False,
                        reason="arquivo mudou desde a última inspeção (estale)",
                        relevance=relevance,
                        size=insp.size,
                        stale=True,
                    )
                )
                continue
            if relevance < _MIN_RELEVANCE and not _matches_objective(objective, insp):
                candidates.append(
                    FileSelection(
                        path=insp.path,
                        included=False,
                        reason="baixa relevância para o objetivo",
                        relevance=relevance,
                        size=insp.size,
                        stale=False,
                    )
                )
                continue
            candidates.append(
                FileSelection(
                    path=insp.path,
                    included=True,
                    reason="relevante para o objetivo e dentro do orçamento",
                    relevance=relevance,
                    size=insp.size,
                    stale=False,
                )
            )

        # Ordena candidatos por relevância decrescente e depois por tamanho (menor primeiro).
        candidates.sort(key=lambda s: (-s.relevance, s.size))

        selected: list[FileSelection] = []
        excluded: list[FileSelection] = []
        total_bytes = 0
        budget_respected = True

        for cand in candidates:
            if not cand.included:
                excluded.append(cand)
                continue
            if len(selected) >= max_files:
                cand.included = False
                cand.reason = "limite máximo de arquivos atingido"
                excluded.append(cand)
                continue
            if total_bytes + cand.size > budget_bytes and total_bytes > 0:
                cand.included = False
                cand.reason = "orçamento de bytes esgotado"
                excluded.append(cand)
                budget_respected = False
                continue
            selected.append(cand)
            total_bytes += cand.size

        estimated_tokens = max(1, total_bytes // _CHARS_PER_TOKEN)
        explanation = (
            f"{len(selected)} arquivo(s) selecionado(s) de {len(candidates)} inspecionado(s); "
            f"{total_bytes} bytes (~{estimated_tokens} tokens); "
            f"orçamento {'respeitado' if budget_respected else 'esgotado'}"
        )

        return ContextReduction(
            selected=selected,
            excluded=excluded,
            total_bytes=total_bytes,
            estimated_tokens=estimated_tokens,
            budget_respected=budget_respected,
            explanation=explanation,
        )

    def memory_summary(self, task_id: Any, *, layer_budget: int = 480) -> str:
        """Devolve o resumo da camada de memória imediata da tarefa, pronto para o prompt."""
        task = self._session.get(TaskModel, task_id)
        if task is None:
            return ""
        return self._memories.summary_for_prompt(task, layer_budget=layer_budget)


def _is_stale(insp: FileInspection, root_path: str) -> bool:
    from pathlib import Path

    from agent.memory.inspection import sha256_file

    current = sha256_file(Path(root_path) / insp.path)
    return current != insp.hash and current != ""


def _matches_objective(objective: str, insp: FileInspection) -> bool:
    if not objective or not insp.summary and not insp.snippets:
        return False
    words = {w.lower() for w in re.findall(r"\w{4,}", objective)}
    text = f"{insp.summary} {' '.join(insp.snippets)}".lower()
    return any(w in text for w in words)
