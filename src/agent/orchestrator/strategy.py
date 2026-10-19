# src/agent/orchestrator/strategy.py — Camada de Abordagem Profissional e Estratégia Executável
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ProfessionalStrategy:
    """Estratégia executável formulada para o pedido, preservando a intenção original."""
    original_request: str
    complexity: str  # "simple", "moderate", "complex"
    domain: str
    lead_specialty: str
    review_specialties: list[str] = field(default_factory=list)
    extracted_requirements: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    execution_sequence: list[dict[str, Any]] = field(default_factory=list)
    verification_strategy: dict[str, Any] = field(default_factory=dict)
    required_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Ordem de complexidade — usada para dimensionar decomposição e orçamento.
    COMPLEXITY_RANK = {"simple": 0, "moderate": 1, "complex": 2}

    @property
    def complexity_rank(self) -> int:
        """Nível de complexidade (0 = simples, 1 = moderado, 2 = complexo)."""
        return self.COMPLEXITY_RANK.get(self.complexity, 1)

    @property
    def needs_atomization(self) -> bool:
        """Indica se a etapa interna deve ser subdividida recursivamente.

        Tarefas simples são executadas como folha; as complexas pedem decomposição
        adaptativa em diagnóstico → correção → verificação.
        """
        return self.complexity_rank >= 2

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["complexity_rank"] = self.complexity_rank
        data["needs_atomization"] = self.needs_atomization
        return data

    def render_summary(self) -> str:
        """Gera um resumo estruturado da estratégia para inspeção e contexto."""
        lines = [
            f"**Domínio:** {self.domain} | **Complexidade:** {self.complexity}",
            f"**Especialidade líder:** {self.lead_specialty}",
        ]
        if self.review_specialties:
            lines.append(f"**Especialidades revisoras:** {', '.join(self.review_specialties)}")
        if self.extracted_requirements:
            lines.append("**Requisitos identificados:**")
            for req in self.extracted_requirements:
                lines.append(f"- {req}")
        if self.risks:
            lines.append("**Riscos e restrições:**")
            for risk in self.risks:
                lines.append(f"- {risk}")
        if self.acceptance_criteria:
            lines.append("**Critérios de aceitação:**")
            for crit in self.acceptance_criteria:
                lines.append(f"- {crit}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProfessionalStrategy | None":
        """Reconstrói a estratégia a partir do dicionário gravado nos metadados da tarefa."""
        if not data:
            return None
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in fields}
        if not kwargs.get("original_request") or not kwargs.get("lead_specialty"):
            return None
        try:
            return cls(**kwargs)
        except TypeError:
            return None


class ProfessionalStrategist:
    """Planejador de abordagem profissional adaptado ao domínio da tarefa.

    Preserva a intenção original do usuário de forma imutável, identifica especialidades
    necessárias, extrai requisitos e constrói uma estratégia executável proporcional.
    """

    def analyze(self, objective: str, *, context_summary: str = "") -> ProfessionalStrategy:
        clean_obj = objective.strip()
        lower = clean_obj.lower()
        words = set(re.findall(r"\w+", lower))

        # 1. Detecção de complexidade e tipo de pedido
        is_simple_query = (
            len(words) < 8
            and not any(w in words for w in ("crie", "implemente", "corrija", "refatore", "altere", "edite", "teste"))
            and any(lower.startswith(prefix) for prefix in ("o que", "como", "qual", "quem", "onde", "quando", "por que", "liste", "mostre"))
        )

        is_bugfix = any(w in words for w in ("bug", "erro", "falha", "corrigir", "consertar", "quebrou", "crash", "fix", "exceção"))
        is_refactor = any(w in words for w in ("refatorar", "refatore", "refatoração", "limpar", "desacoplar", "simplificar"))
        is_doc = any(w in words for w in ("documentar", "documente", "readme", "resume", "docs", "manual", "guia"))
        is_architecture = any(w in words for w in ("arquitetura", "decompor", "subsistema", "design", "redesenhar"))
        is_feature = any(w in words for w in ("crie", "implemente", "adicione", "desenvolva", "construa", "novo", "nova"))
        is_qa = any(
            w in words
            for w in ("teste", "testes", "testar", "verificação", "verificar", "validar", "homologar", "qualidade", "cobertura")
        )
        is_fix_request = any(w in words for w in ("corrigir", "consertar", "corrigir", "fix", "reparar"))

        # Verificação/qualidade tem precedência sobre bugfix quando o pedido é só comprovar
        # (sem pedir implementação nem correção).
        if is_qa and not is_fix_request and not is_feature:
            return ProfessionalStrategy(
                original_request=clean_obj,
                complexity="moderate" if len(words) > 12 else "simple",
                domain="quality_assurance",
                lead_specialty="testing_quality_assurance",
                review_specialties=["software_engineering"],
                extracted_requirements=[
                    f"Comprovar de forma objetiva: {clean_obj}",
                    "Produzir evidência reproduzível (execução real, saída e código de retorno)",
                ],
                assumptions=["Existe suíte de testes ou comando de verificação disponível."],
                risks=[
                    "Concluir sem evidência executada",
                    "Verificação frágil que não cobre o comportamento exigido",
                ],
                acceptance_criteria=[
                    "Verificação executada com código de saída 0",
                    "Evidência registrada com o artefato avaliado",
                ],
                execution_sequence=[
                    {"title": "Mapear critérios de aceitação", "kind": "PLANNING", "action": "planejar"},
                    {"title": "Executar verificação independente", "kind": "VERIFICATION", "action": "verificar"},
                ],
                verification_strategy={"type": "pytest", "description": "Execução de testes automatizados"},
                required_tools=["pytest_run", "shell_exec", "file_read"],
            )

        if is_simple_query:
            return ProfessionalStrategy(
                original_request=clean_obj,
                complexity="simple",
                domain="consultation",
                lead_specialty="consultor_tecnico",
                review_specialties=[],
                extracted_requirements=[clean_obj],
                assumptions=["Pedido direto de informação ou consulta que não exige alterações de código."],
                risks=["Possível resposta desatualizada se não consultar arquivos locais quando pertinente."],
                acceptance_criteria=["Resposta objetiva, precisa e fundamentada."],
                execution_sequence=[
                    {"title": "Responder consulta", "kind": "CLOSING", "description": clean_obj}
                ],
                verification_strategy={"type": "syntax", "description": "Validação de formato"},
                required_tools=[],
            )

        # 2. Tarefas técnicas de engenharia
        if is_bugfix:
            complexity = "complex" if len(words) > 15 else "moderate"
            return ProfessionalStrategy(
                original_request=clean_obj,
                complexity=complexity,
                domain="debugging_and_root_cause",
                lead_specialty="debugging_root_cause",
                review_specialties=["testing_quality_assurance", "software_engineering"],
                extracted_requirements=[
                    f"Identificar e isolar a causa fundamental de: {clean_obj}",
                    "Aplicar correção cirúrgica no código fonte sem mascarar sintomas",
                    "Garantir não-regressão através de testes automatizados",
                ],
                assumptions=["Existe evidência reproduzível ou teste indicando a falha."],
                risks=[
                    "Mascarar o defeito com tratamento superficial",
                    "Quebrar comportamentos correlacionados",
                ],
                acceptance_criteria=[
                    "Falha reproduzida e eliminada na causa raiz",
                    "Todos os testes relevantes passam com sucesso",
                ],
                execution_sequence=[
                    {"title": "Reprodução e diagnóstico da causa raiz", "kind": "MODEL_OPERATION", "action": "diagnosticar"},
                    {"title": "Implementação da correção cirúrgica", "kind": "MODEL_OPERATION", "action": "corrigir"},
                    {"title": "Verificação de não-regressão", "kind": "VERIFICATION", "action": "testar"},
                ],
                verification_strategy={"type": "pytest", "description": "Execução de testes automatizados"},
                required_tools=["file_read", "file_edit", "pytest_run", "grep_search"],
            )

        if is_refactor:
            return ProfessionalStrategy(
                original_request=clean_obj,
                complexity="moderate",
                domain="refactoring",
                lead_specialty="refactoring_clean_code",
                review_specialties=["testing_quality_assurance", "system_architecture"],
                extracted_requirements=[
                    f"Refatorar conforme solicitado: {clean_obj}",
                    "Preservar 100% da compatibilidade e comportamento externo",
                ],
                assumptions=["A base de código possui testes cobrindo o comportamento atual."],
                risks=["Alteração indesejada de comportamento em casos de borda."],
                acceptance_criteria=[
                    "Código mais limpo e modular",
                    "Todos os testes pré-existentes continuam passando",
                ],
                execution_sequence=[
                    {"title": "Inspeção e análise de estrutura", "kind": "MODEL_OPERATION", "action": "inspecionar"},
                    {"title": "Refatoração incremental", "kind": "MODEL_OPERATION", "action": "refatorar"},
                    {"title": "Validação de regressão", "kind": "VERIFICATION", "action": "testar"},
                ],
                verification_strategy={"type": "pytest", "description": "Validação de regressão total"},
                required_tools=["file_read", "file_edit", "pytest_run"],
            )

        if is_doc:
            return ProfessionalStrategy(
                original_request=clean_obj,
                complexity="simple" if len(words) < 10 else "moderate",
                domain="documentation",
                lead_specialty="technical_writing",
                review_specialties=["software_engineering"],
                extracted_requirements=[f"Documentar conforme solicitado: {clean_obj}"],
                assumptions=["A documentação deve refletir o código implementado real."],
                risks=["Inconsistência entre código e documentação."],
                acceptance_criteria=["Documentação clara, navegável e sincronizada."],
                execution_sequence=[
                    {"title": "Levantamento de informações e código", "kind": "MODEL_OPERATION", "action": "levantar"},
                    {"title": "Redação e atualização técnica", "kind": "MODEL_OPERATION", "action": "escrever"},
                    {"title": "Verificação de integridade e links", "kind": "VERIFICATION", "action": "verificar"},
                ],
                verification_strategy={"type": "file_contains", "description": "Verificação de artefatos criados"},
                required_tools=["file_read", "file_write", "file_edit"],
            )

        # Caso geral: Engenharia de Software / Feature
        complexity = "complex" if len(words) > 12 else "moderate"
        lead = "system_architecture" if is_architecture else "software_engineering"
        reviewers = ["testing_quality_assurance"]
        if is_architecture:
            reviewers.append("software_engineering")

        return ProfessionalStrategy(
            original_request=clean_obj,
            complexity=complexity,
            domain="software_engineering",
            lead_specialty=lead,
            review_specialties=reviewers,
            extracted_requirements=[
                f"Atender ao objetivo: {clean_obj}",
                "Preservar a arquitetura modular e padrões do projeto",
                "Garantir cobertura por testes e critérios de validação objetivos",
            ],
            assumptions=["O ambiente dispõe das ferramentas necessárias para build e teste."],
            risks=[
                "Impacto em contratos de API preexistentes",
                "Complexidade desnecessária ou acoplamento excessivo",
            ],
            acceptance_criteria=[
                "Implementação completa e testada",
                "Ausência de erros de sintaxe ou execução",
                "Critérios de aceite comprovados por evidências",
            ],
            execution_sequence=[
                {"title": "Análise de requisitos e contexto", "kind": "PLANNING", "action": "planejar"},
                {"title": "Implementação modular", "kind": "MODEL_OPERATION", "action": "implementar"},
                {"title": "Verificação e validação de qualidade", "kind": "VERIFICATION", "action": "validar"},
            ],
            verification_strategy={"type": "pytest", "description": "Testes automatizados e verificação de integridade"},
            required_tools=["file_read", "file_write", "file_edit", "pytest_run", "shell_exec"],
        )
