# src/agent/skills/models.py — Contrato formal e modelos de dados para Skills
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillMatch:
    """Resultado do matching entre uma tarefa e uma Skill."""
    skill_id: str
    skill_name: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class SkillSpec:
    """Contrato formal de uma Skill do Agente.

    Representa uma competência reutilizável contendo instruções, condições de ativação,
    regras de não-uso, procedimentos passo a passo, ferramentas autorizadas e
    critérios de validação.
    """
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    activation_criteria: list[str] = field(default_factory=list)
    prohibited_criteria: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    applies_to_kinds: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Valida a integridade do contrato da Skill. Retorna lista de erros."""
        errors: list[str] = []
        if not self.id or not self.id.strip():
            errors.append("Skill sem 'id' válido")
        if not self.name or not self.name.strip():
            errors.append(f"Skill '{self.id}' sem 'name'")
        if not self.description or not self.description.strip():
            errors.append(f"Skill '{self.id}' sem 'description'")
        if not self.procedures and not self.activation_criteria:
            errors.append(f"Skill '{self.id}' sem procedimentos nem critérios de ativação")
        return errors

    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    def render_prompt_instructions(self, max_chars: int = 1500) -> str:
        """Gera o bloco condensado de instruções da Skill para injeção no prompt de execução."""
        parts = [f"### Skill: {self.name} (`{self.id}`)"]
        if self.description:
            parts.append(f"**Finalidade:** {self.description}")
        if self.procedures:
            parts.append("**Procedimentos operacionais:**")
            for i, step in enumerate(self.procedures, 1):
                parts.append(f"{i}. {step}")
        if self.validation_rules:
            parts.append("**Critérios de validação:**")
            for rule in self.validation_rules:
                parts.append(f"- {rule}")
        if self.risk_factors:
            parts.append("**Controle de riscos:**")
            for risk in self.risk_factors:
                parts.append(f"- {risk}")
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars - 20] + "\n...[instruções condensadas]"
        return text
