"""
Arquivo: src/agent/orchestrator/atomizer.py
Nome: atomizer.py
Propósito: decisão de atomização recursiva e adaptativa.
Responsabilidade: camada de aplicação.
Componentes: complexity_score, should_decompose_further, depth_guard, adaptive_decompose_operation, micro_decompose_operation.
Dependências: agent.domain.enums, agent.orchestrator.decomposition, __future__, re, typing.
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""

from __future__ import annotations

import re
from typing import Any

from agent.domain.enums import TaskKind
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec


def complexity_score(*, objective: str, metadata: dict | None, kind: str, attempt_count: int) -> int:
    """Dá uma nota de complexidade à etapa, para decidir se ela ainda deve ser dividida.

    Args:
        objective: texto do objetivo da etapa.
        metadata: metadados da etapa, que revelam operação de modelo e atomização pedida.
        kind: tipo da tarefa.
        attempt_count: número de tentativas já feitas na etapa.

    Returns:
        A pontuação acumulada; quanto maior, mais complexa a etapa parece.
    """
    score = 0
    meta = metadata or {}
    score += min(len(objective) // 40, 5)
    # A quantidade de chaves do metadado não é complexidade: uso, inspeção e pausa
    # incham o dicionário e fariam a etapa se dividir sem necessidade.
    if kind in (TaskKind.SUBSYSTEM.value, "SUBSYSTEM", "OBJECTIVE"):
        score += 2
    if meta.get("model_operation"):
        score += 3
    if attempt_count >= 2:
        score += 2
    if meta.get("atomize"):
        score += 5
    return score


def should_decompose_further(
    *,
    objective: str,
    metadata: dict | None,
    kind: str,
    attempt_count: int,
    has_children: bool,
    threshold: int = 6,
    depth: int = 0,
    max_depth: int = 3,
) -> bool:
    """Decide se a etapa interna ainda deve ser dividida.

    Entradas: objetivo, metadados, tipo, tentativas, se já tem filhos, profundidade atual e
    profundidade máxima. Saída: `True` quando vale subdividir de novo.

    A profundidade máxima impede recursão infinita: abaixo do limite, a decisão depende do
    gatilho explícito (`atomize`), da complexidade e das tentativas.
    """
    if has_children:
        return False
    meta = metadata or {}
    if meta.get("atomic"):
        return False
    if depth >= max_depth:
        return False
    if meta.get("atomize"):
        return True
    if meta.get("tool") or meta.get("verification"):
        return False
    return complexity_score(
        objective=objective, metadata=metadata, kind=kind, attempt_count=attempt_count
    ) >= threshold


def depth_guard(
    *,
    depth: int,
    max_depth: int,
    parent_title: str = "",
    sibling_titles: list[str] | None = None,
) -> str | None:
    """Proteção contra recursão e ciclos na decomposição recursiva.

    Entradas: profundidade atual, profundidade máxima, título do pai e títulos irmãos.
    Saída: motivo do bloqueio ou `None` quando a decomposição pode seguir.
    """
    if depth >= max_depth:
        return f"profundidade de proteção ({max_depth}) atingida"
    parent = (parent_title or "").strip().casefold()
    siblings = {t.strip().casefold() for t in (sibling_titles or []) if t and t.strip()}
    if parent and parent in siblings:
        return "o plano repetiria um título de etapa já existente"
    return None


def adaptive_decompose_operation(
    objective: str,
    *,
    metadata: dict[str, Any] | None = None,
    lead_specialty: str | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> DecompositionResult:
    """Decomposição adaptativa que escolhe subetapas com base no domínio e especialidade da tarefa.

    Entradas: objetivo da etapa, metadados, especialidade líder e profundidade (com o limite).
    Saída: `DecompositionResult` com as subtarefas — ou uma única etapa atômica quando a
    profundidade máxima foi atingida (a decomposição recursiva para ali).

    A verificação das subetapas é `stages` (a etapa anterior concluiu com evidência) e não
    `pytest`: a decomposição acontece antes de o agente saber o que o projeto tem, e um
    verificador que pressupõe uma pasta de testes que não existe reprovaria a etapa por um
    motivo que não é do trabalho.
    """
    lower = objective.lower()
    meta = metadata or {}
    specialty = lead_specialty or meta.get("lead_specialty") or ""

    if depth >= max_depth:
        return DecompositionResult(
            subtasks=[
                SubTaskSpec(
                    title="Executar etapa complexa de forma atômica",
                    objective=objective,
                    metadata={"model_operation": True, "atomic": True, "lead_specialty": specialty},
                )
            ]
        )

    # 1. Ramo de Depuração / Análise de causa raiz
    is_bug = specialty == "debugging_root_cause" or any(
        w in lower for w in ("bug", "erro", "falha", "corrigir", "consertar", "quebrou", "crash", "fix")
    )
    if is_bug:
        return DecompositionResult(
            subtasks=[
                SubTaskSpec(
                    title="Reproduzir e diagnosticar causa raiz",
                    objective=f"Reproduzir e isolar a causa fundamental de: {objective[:140]}",
                    metadata={"tool": "run_pytest", "tool_args": {"path": "."}, "atomic": True, "lead_specialty": "debugging_root_cause"},
                ),
                SubTaskSpec(
                    title="Aplicar correção cirúrgica",
                    objective=f"Corrigir causa raiz identificada: {objective}",
                    metadata={"model_operation": True, "atomic": True, "lead_specialty": "software_engineering"},
                    depends_on_indices=[0],
                ),
                SubTaskSpec(
                    title="Verificar não-regressão",
                    objective="Executar testes automatizados para validar que o defeito foi corrigido e não há regressão",
                    metadata={"verification": {"type": "stages"}, "atomic": True, "lead_specialty": "testing_quality_assurance"},
                    depends_on_indices=[1],
                ),
            ]
        )

    # 2. Ramo de Refatoração
    is_refactor = specialty == "refactoring_clean_code" or any(
        w in lower for w in ("refatorar", "refatoração", "clean code", "simplificar", "desacoplar")
    )
    if is_refactor:
        return DecompositionResult(
            subtasks=[
                SubTaskSpec(
                    title="Inspecionar estrutura atual",
                    objective=f"Analisar o código e acoplamentos antes da refatoração: {objective[:140]}",
                    metadata={"tool": "search_grep", "tool_args": {"pattern": "def "}, "atomic": True, "lead_specialty": "system_architecture"},
                ),
                SubTaskSpec(
                    title="Refatorar incrementalmente",
                    objective=f"Aplicar refatoração preservando comportamento: {objective}",
                    metadata={"model_operation": True, "atomic": True, "lead_specialty": "refactoring_clean_code"},
                    depends_on_indices=[0],
                ),
                SubTaskSpec(
                    title="Validar paridade de comportamento",
                    objective="Confirmar que todos os testes existentes passam sem alteração funcional",
                    metadata={"verification": {"type": "stages"}, "atomic": True, "lead_specialty": "testing_quality_assurance"},
                    depends_on_indices=[1],
                ),
            ]
        )

    # 3. Ramo de Documentação
    is_doc = specialty == "technical_writing" or any(
        w in lower for w in ("documentar", "documentação", "readme", "resume", "docs", "guia")
    )
    if is_doc:
        return DecompositionResult(
            subtasks=[
                SubTaskSpec(
                    title="Inspecionar referências do código",
                    objective="Listar arquivos e símbolos que devem ser documentados",
                    metadata={"tool": "list_dir", "tool_args": {"path": "."}, "atomic": True, "lead_specialty": "technical_writing"},
                ),
                SubTaskSpec(
                    title="Escrever documentação técnica",
                    objective=f"Elaborar documentação solicitada: {objective}",
                    metadata={"model_operation": True, "atomic": True, "lead_specialty": "technical_writing"},
                    depends_on_indices=[0],
                ),
                SubTaskSpec(
                    title="Validar integridade da documentação",
                    objective="Conferir que os arquivos e referências criados estão consistentes",
                    metadata={"verification": {"type": "stages"}, "atomic": True, "lead_specialty": "technical_writing"},
                    depends_on_indices=[1],
                ),
            ]
        )

    # 4. Ramo Padrão / Engenharia Modular
    return DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Inspecionar contexto",
                objective=f"Buscar referências e símbolos relacionados: {objective[:120]}",
                metadata={"tool": "search_grep", "tool_args": {"pattern": "def "}, "atomic": True},
            ),
            SubTaskSpec(
                title="Executar alteração",
                objective=objective,
                metadata={"model_operation": True, "atomic": True},
                depends_on_indices=[0],
            ),
            SubTaskSpec(
                title="Verificar alteração",
                objective="Rodar verificação determinística",
                metadata={"verification": {"type": "stages"}, "atomic": True},
                depends_on_indices=[1],
            ),
        ]
    )


def micro_decompose_operation(objective: str) -> DecompositionResult:
    """Compatibilidade retroativa: delega para adaptive_decompose_operation."""
    return adaptive_decompose_operation(objective)
