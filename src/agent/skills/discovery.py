# src/agent/skills/discovery.py — Descoberta, validação e catálogo de Skills
from __future__ import annotations

import logging
from pathlib import Path

from agent.skills.builtins import get_builtin_skills
from agent.skills.catalog.loader import catalog_dir, load_catalog
from agent.skills.models import SkillSpec

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Registro e catálogo central de Skills do Agente.

    Carrega, nesta ordem de precedência:

    1. **Skills embutidas** (`agent.skills.builtins`) — garantia offline, sempre presentes;
    2. **Catálogo do repositório** (`skills/*.md`) — fonte de verdade das competências
       profissionais, com metadados completos (critérios, proibições, procedimentos,
       validação, riscos, ferramentas e palavras-chave);
    3. **Skills do projeto** (`<project_root>/skills/*.md`) — competências específicas do
       projeto, que sobrescrevem as anteriores por identificador.
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self._skills: dict[str, SkillSpec] = {}
        self._invalid_skills: dict[str, list[str]] = {}
        self._sources: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Recarrega o catálogo de Skills a partir das built-ins e dos diretórios de skills."""
        self._skills.clear()
        self._invalid_skills.clear()
        self._sources.clear()

        # 1. Built-ins (fallback offline garantido).
        for skill in get_builtin_skills():
            self._register(skill, source="builtin")

        # 2. Catálogo do repositório (fonte de verdade) e do projeto.
        for directory in self._catalog_dirs():
            for skill in load_catalog(directory, strict=False):
                self._register(skill, source=str(directory))

    def _catalog_dirs(self) -> list[Path]:
        """Diretórios de catálogo, do mais específico (projeto) ao mais genérico (repositório)."""
        dirs: list[Path] = []
        if self.project_root:
            project_skills = self.project_root / "skills"
            if project_skills.is_dir():
                dirs.append(project_skills)
        generic = catalog_dir(self.project_root)
        if generic is not None and generic not in dirs:
            dirs.append(generic)
        return dirs

    def _register(self, skill: SkillSpec, *, source: str) -> None:
        errors = skill.validate()
        if errors:
            self._invalid_skills[skill.id] = errors
            logger.warning("Skill inválida %s (%s): %s", skill.id, source, errors)
            return
        self._skills[skill.id] = skill
        self._sources[skill.id] = source

    def source_of(self, skill_id: str) -> str | None:
        """Origem da Skill carregada (`builtin` ou caminho do catálogo)."""
        return self._sources.get(skill_id)

    def register(self, skill: SkillSpec) -> None:
        """Registra uma Skill programaticamente."""
        errors = skill.validate()
        if errors:
            self._invalid_skills[skill.id] = errors
            raise ValueError(f"Skill inválida: {errors}")
        self._skills[skill.id] = skill
        self._sources[skill.id] = "runtime"

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(skill_id)

    def list_all(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def list_invalid(self) -> dict[str, list[str]]:
        return dict(self._invalid_skills)


_default_registry: SkillRegistry | None = None


def get_skill_registry(project_root: str | Path | None = None) -> SkillRegistry:
    """Retorna a instância do registro de Skills (singleton por raiz de projeto)."""
    global _default_registry
    if _default_registry is None or (project_root and _default_registry.project_root != Path(project_root).resolve()):
        _default_registry = SkillRegistry(project_root)
    return _default_registry


def reset_skill_registry() -> None:
    """Descarta o singleton (usado em testes e ao trocar de projeto em runtime)."""
    global _default_registry
    _default_registry = None
