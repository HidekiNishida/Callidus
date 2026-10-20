"""
Arquivo: src/agent/skills/__init__.py
Nome: __init__.py
Propósito: expor o pacote de Skills do Agente (catálogo, descoberta e seleção de competências).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.skills`.
Componentes: SkillSpec, SkillMatch, SkillRegistry, SkillSelector, get_builtin_skills, load_catalog, parse_skill_markdown.
Dependências: agent.skills.builtins, agent.skills.catalog, agent.skills.discovery, agent.skills.models, agent.skills.selector.
Observações: o registro de skills é um singleton reinicializável (usado nos testes).
"""
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
