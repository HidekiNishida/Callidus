# src/agent/skills/selector.py — Seleção dinâmica e econômica de Skills sob demanda
from __future__ import annotations

import re
from typing import Sequence

from agent.skills.discovery import SkillRegistry, get_skill_registry
from agent.skills.models import SkillMatch, SkillSpec

# Verbos de escrita/alteração: sua presença significa que a tarefa muda o repositório.
_ACTION_WORDS = {
    "crie", "criar", "criação", "criando",
    "altere", "alterar", "alteração",
    "edite", "editar", "edição",
    "modifique", "modificar", "modificação",
    "escreva", "escrever", "escrita",
    "implemente", "implementar", "implementação",
    "adicione", "adicionar",
    "refatore", "refatorar",
    "corrija", "corrigir", "correção",
    "consertar", "remover", "renomear", "mover",
}

# Verbos de leitura pura: pedem consulta, não alteração.
_READ_WORDS = {
    "leia", "ler", "leitura", "veja", "ver", "liste", "listar",
    "consulte", "consultar", "mostre", "mostrar", "explique", "explicar",
    "descreva", "descrever", "analise", "analisar", "revise", "revisar",
    "busque", "buscar", "encontre", "encontrar",
}

# Fragmentos que indicam "apenas leitura" dentro de um critério de proibição.
_READ_ONLY_MARKERS = (
    "sem alteração",
    "sem alterar",
    "sem alterar código",
    "somente leitura",
    "apenas leitura",
    "read-only",
    "purely reads",
    "sem modificar",
)


def _word_pattern(term: str) -> re.Pattern[str]:
    """Padrão de palavra inteira: evita que `api` case dentro de `rapido`."""
    return re.compile(rf"(?<!\w){re.escape(term.lower())}(?!\w)")


class SkillSelector:
    """Motor de seleção inteligente de Skills sob demanda.

    Avalia o objetivo da tarefa, tipo de operação, ferramentas disponíveis e
    orçamento de contexto para selecionar as competências mais adequadas,
    garantindo que prompts permaneçam enxutos e focados.
    """

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or get_skill_registry()

    def select(
        self,
        objective: str,
        *,
        task_kind: str | None = None,
        available_tools: Sequence[str] | None = None,
        max_skills: int = 2,
    ) -> list[SkillMatch]:
        """Seleciona até `max_skills` competências relevantes para o objetivo."""
        if not objective or max_skills <= 0:
            return []

        lower_obj = objective.lower()
        words = set(re.findall(r"\w+", lower_obj))
        matches: list[SkillMatch] = []
        tools_set = set(available_tools or [])

        for skill in self.registry.list_all():
            if self._prohibited(skill, lower_obj, words):
                continue

            score = 0.0
            reasons: list[str] = []

            # 1. Correspondência por palavras-chave do objetivo (palavra inteira).
            matched_keywords = [kw for kw in skill.keywords if kw and _word_pattern(kw).search(lower_obj)]
            if matched_keywords:
                score += len(matched_keywords) * 2.0
                reasons.append(f"palavras-chave encontradas: {', '.join(matched_keywords[:3])}")

            # 2. Correspondência por tipo de tarefa (kind).
            if task_kind and skill.applies_to_kinds:
                if task_kind in skill.applies_to_kinds:
                    score += 1.5
                    reasons.append(f"aplicável ao tipo {task_kind}")

            # 3. Correspondência de ferramentas autorizadas.
            if tools_set and skill.required_tools:
                common_tools = tools_set.intersection(set(skill.required_tools))
                if common_tools:
                    score += len(common_tools) * 0.5
                    reasons.append(f"ferramentas compatíveis: {', '.join(sorted(common_tools)[:3])}")

            # 4. Correspondência por critérios de ativação declarados.
            if skill.activation_criteria:
                hit = [c for c in skill.activation_criteria if _overlaps(c, lower_obj)]
                if hit:
                    score += 1.0
                    reasons.append(f"critério de ativação atendido: {hit[0][:60]}")

            if score > 0.0:
                matches.append(
                    SkillMatch(
                        skill_id=skill.id,
                        skill_name=skill.name,
                        score=score,
                        reasons=reasons,
                    )
                )

        matches.sort(key=lambda m: (-m.score, m.skill_id))
        return matches[:max_skills]

    def select_for_strategy(
        self,
        strategy: object,
        *,
        task_kind: str | None = None,
        available_tools: Sequence[str] | None = None,
        max_skills: int = 2,
    ) -> list[SkillMatch]:
        """Seleciona Skills a partir de uma `ProfessionalStrategy`.

        A especialidade líder da estratégia entra com peso máximo; as especialidades
        revisoras completam o time, sempre respeitando o limite de skills.
        """
        objective = str(getattr(strategy, "original_request", "") or "")
        lead = str(getattr(strategy, "lead_specialty", "") or "")
        reviewers = [str(x) for x in (getattr(strategy, "review_specialties", None) or [])]
        matches = self.select(
            objective,
            task_kind=task_kind,
            available_tools=available_tools,
            max_skills=max_skills,
        )
        chosen: list[SkillMatch] = []
        by_id = {m.skill_id: m for m in matches}

        if lead and lead in by_id:
            match = by_id[lead]
            match.score += 10.0
            match.reasons.insert(0, "especialidade líder da estratégia")
            chosen.append(match)
        for reviewer in reviewers:
            if len(chosen) >= max_skills:
                break
            if reviewer in by_id and reviewer not in {m.skill_id for m in chosen}:
                match = by_id[reviewer]
                match.score += 5.0
                match.reasons.insert(0, "especialidade revisora da estratégia")
                chosen.append(match)

        for match in matches:
            if len(chosen) >= max_skills:
                break
            if match.skill_id not in {m.skill_id for m in chosen}:
                chosen.append(match)

        chosen.sort(key=lambda m: (-m.score, m.skill_id))
        return chosen[:max_skills]

    def _prohibited(self, skill: SkillSpec, lower_obj: str, words: set[str]) -> bool:
        """Aplica os critérios de não-ativação da Skill ao objetivo."""
        if not skill.prohibited_criteria:
            return False
        read_only_intent = bool(words & _READ_WORDS) and not (words & _ACTION_WORDS)
        for crit in skill.prohibited_criteria:
            crit_lower = crit.lower()
            if any(marker in crit_lower for marker in _READ_ONLY_MARKERS) and read_only_intent:
                return True
            # Critério escrito como frase negativa direta: "não use para X".
            if crit_lower.startswith(("não use", "nao use", "never use")):
                target = re.split(r"\bpara\b|\bwhen\b|\bfor\b", crit_lower, maxsplit=1)
                if len(target) > 1 and _overlaps(target[1], lower_obj):
                    return True
        return False

    def render_selected_skills(
        self,
        matches: list[SkillMatch],
        *,
        max_chars: int = 2500,
    ) -> str:
        """Gera bloco de texto formatado com as instruções das Skills selecionadas."""
        if not matches or max_chars <= 0:
            return ""

        header = "## Competências e Procedimentos de Especialidade (Skills Aplicadas)\n"
        budget = max_chars - len(header)
        if budget <= 0:
            return ""

        blocks: list[str] = []
        chars_used = 0
        per_skill = max(200, budget // max(1, len(matches)))

        for match in matches:
            skill = self.registry.get(match.skill_id)
            if not skill:
                continue
            rendered = skill.render_prompt_instructions(max_chars=per_skill)
            if chars_used + len(rendered) > budget:
                break
            blocks.append(rendered)
            chars_used += len(rendered)

        if not blocks:
            return ""
        return header + "\n\n".join(blocks)


def _overlaps(phrase: str, lower_obj: str) -> bool:
    """True quando ao menos uma palavra significativa da frase aparece no objetivo."""
    words = [w for w in re.findall(r"\w+", phrase.lower()) if len(w) > 3]
    if not words:
        return False
    return any(_word_pattern(w).search(lower_obj) for w in words)
