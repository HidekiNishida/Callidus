"""
Arquivo: src/agent/skills/authoring/__init__.py
Nome: __init__.py
Propósito: expor a infraestrutura de autoria, ciclo de vida e versionamento de skills.
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.skills.authoring`.
Componentes: SkillLayout, SkillStore, SkillAuthoringService, validação e manifesto.
Dependências: agent.skills.authoring.*.
Observações: autoria, validação, instalação, ativação e execução são etapas separadas.
"""
from __future__ import annotations

from agent.skills.authoring.layout import (
    MANIFEST_FILE,
    SKILL_FILE,
    SUBDIRS,
    SkillLayout,
    default_manifest,
    render_manifest,
    render_skill_md,
)
from agent.skills.authoring.service import Proposal, SkillAuthoringService
from agent.skills.authoring.store import InstalledSkill, SkillStore, hash_tree
from agent.skills.authoring.validator import (
    ValidationResult,
    validate_name,
    validate_skill,
)

__all__ = [
    "MANIFEST_FILE",
    "SKILL_FILE",
    "SUBDIRS",
    "InstalledSkill",
    "Proposal",
    "SkillAuthoringService",
    "SkillLayout",
    "SkillStore",
    "ValidationResult",
    "default_manifest",
    "hash_tree",
    "render_manifest",
    "render_skill_md",
    "validate_name",
    "validate_skill",
]
