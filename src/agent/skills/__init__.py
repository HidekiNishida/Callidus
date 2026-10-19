# src/agent/skills/__init__.py — Pacote de Skills do Agente
from __future__ import annotations

from agent.skills.builtins import get_builtin_skills
from agent.skills.catalog import load_catalog, parse_skill_markdown
from agent.skills.discovery import SkillRegistry, get_skill_registry, reset_skill_registry
from agent.skills.models import SkillMatch, SkillSpec
from agent.skills.selector import SkillSelector

__all__ = [
    "SkillSpec",
    "SkillMatch",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    "SkillSelector",
    "get_builtin_skills",
    "load_catalog",
    "parse_skill_markdown",
]
