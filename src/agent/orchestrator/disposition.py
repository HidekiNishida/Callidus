"""
Arquivo: src/agent/orchestrator/disposition.py
Nome: disposition.py
Propósito: escolher executar, investigar, decompor ou replanejar sem criar árvore à toa.
Responsabilidade: camada de aplicação — decisão determinística antes da decomposição adaptativa.
Componentes: Disposition, decide_disposition, investigation_plan.
Dependências: agent.orchestrator.decomposition, re.
Observações: a decisão só substitui o atomizador quando a etapa já foi marcada para subdividir;
o plano da raiz continua no planejador existente.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec
from agent.orchestrator.requirements import evidence_kind

_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.MULTILINE)
_UNCERTAIN = re.compile(
    r"\b(onde fica|onde est[aá]|n[ãa]o sei|qual arquivo|investig\w*|como funciona)\b",
    re.IGNORECASE,
)


@dataclass
class Disposition:
    """Decisão de como tratar a etapa, com o motivo que pode ir para o feed.

    Atributos:
        action: `execute`, `investigate`, `decompose` ou `replan`.
        reason: frase factual, sem justificar o que não foi observado.
        factors: sinais usados na decisão.
    """

    action: str
    reason: str
    factors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serializa a decisão para o metadado da tarefa."""
        return asdict(self)


def decide_disposition(
    *,
    objective: str,
    metadata: dict[str, Any] | None,
    depth: int,
    max_depth: int,
    attempt_count: int,
    strategy: dict[str, Any] | None = None,
) -> Disposition:
    """Escolhe o próximo modo da etapa.

    A ordem é fixa: passo já executável, profundidade de proteção, falha repetida,
    falta de contexto, pedido com várias partes e, por fim, etapa única.

    Args:
        objective: objetivo da etapa.
        metadata: metadados atuais.
        depth: profundidade da etapa na árvore.
        max_depth: profundidade máxima configurada.
        attempt_count: tentativas já gastas nesta etapa.
        strategy: estratégia profissional, quando já existir.

    Returns:
        A decisão e o motivo.
    """
    meta = metadata or {}
    text = " ".join((objective or "").split())
    factors: list[str] = [f"profundidade {depth} de {max_depth}", f"tentativas {attempt_count}"]
    if meta.get("tool") or meta.get("verification") or meta.get("final_answer") or meta.get("atomic"):
        factors.append("a etapa já é um passo fechado")
        return Disposition("execute", "A etapa já tem um passo fechado. Vou executá-la.", factors)
    if meta.get("model_operation") and not meta.get("atomize"):
        factors.append("operação de modelo sem pedido de nova divisão")
        return Disposition("execute", "A etapa já é uma operação. Vou executá-la.", factors)
    if depth >= max_depth:
        factors.append("profundidade de proteção atingida")
        return Disposition(
            "execute",
            f"A profundidade de proteção ({max_depth}) foi atingida. Vou executar esta etapa sem dividir.",
            factors,
        )
    if meta.get("last_failure") and attempt_count >= 2:
        factors.append("falha anterior registrada")
        return Disposition(
            "replan",
            "Esta etapa já falhou. Repetir a mesma divisão não acrescenta evidência; vou seguir com outra abordagem.",
            factors,
        )
    enumerated = len(_ITEM.findall(objective or ""))
    if enumerated:
        factors.append(f"{enumerated} itens enumerados")
    uncertain = bool(_UNCERTAIN.search(text)) and not meta.get("investigated")
    if uncertain:
        factors.append("o pedido não localiza o ponto de mudança")
        return Disposition(
            "investigate",
            "Ainda não sei onde agir no projeto. Vou investigar isso antes de alterar qualquer coisa.",
            factors,
        )
    complexity = str((strategy or {}).get("complexity") or "")
    if enumerated >= 3 or (meta.get("atomize") and complexity == "complex" and len(text) > 280):
        factors.append("o pedido ainda junta partes com resultados diferentes")
        return Disposition(
            "decompose",
            "O pedido ainda junta partes com resultados diferentes. Vou separá-las.",
            factors,
        )
    if meta.get("atomize"):
        factors.append("a etapa marcada para dividir já tem um resultado único")
        return Disposition(
            "execute",
            "Esta etapa já tem um resultado único. Dividir de novo só aumentaria a coordenação, então vou executá-la.",
            factors,
        )
    if complexity == "complex" and len(text) > 280:
        factors.append("estratégia complexa e objetivo longo")
        return Disposition("decompose", "O objetivo ainda é longo para um único passo. Vou dividi-lo.", factors)
    factors.append("objetivo delimitado")
    return Disposition("execute", "O objetivo cabe em um passo. Vou executá-lo.", factors)


def investigation_plan(objective: str, *, read_only: bool = False) -> DecompositionResult:
    """Plano curto: primeiro reunir evidência, depois executar, e verificar se houve mudança.

    A primeira etapa é uma listagem real do diretório. A execução depende dela.
    Pedido somente leitura não ganha etapa de verificação de arquivo.

    Args:
        objective: objetivo que ainda não pode ser alterado às cegas.
        read_only: quando verdadeiro, o plano para na investigação e no relatório.

    Returns:
        O plano de investigação.
    """
    steps = [
        SubTaskSpec(
            title="Investigar o contexto",
            objective=f"Listar o que existe no projeto antes de agir: {objective[:160]}",
            metadata={"tool": "list_dir", "tool_args": {"path": "."}, "atomic": True, "investigation": True},
        ),
        SubTaskSpec(
            title="Agir com o que foi encontrado",
            objective=objective,
            metadata={"model_operation": True, "atomic": True, "investigated": True},
            depends_on_indices=[0],
        ),
    ]
    if evidence_kind(objective) == "change" and not read_only:
        steps.append(
            SubTaskSpec(
                title="Verificar o resultado",
                objective="Conferir o resultado com o verificador disponível. Sem execução, o resultado segue pendente.",
                metadata={"verification": {"type": "stages"}, "atomic": True},
                depends_on_indices=[1],
            )
        )
    return DecompositionResult(subtasks=steps)
