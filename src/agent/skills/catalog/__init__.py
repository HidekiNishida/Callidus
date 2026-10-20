"""
Arquivo: src/agent/skills/catalog/__init__.py
Nome: __init__.py
Propósito: expor o catálogo de Skills em Markdown (fonte de verdade das competências).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.skills.catalog`.
Componentes: load_catalog, parse_skill_markdown, parse_frontmatter, catalog_dir, default_catalog_dir.
Dependências: agent.skills.catalog.loader.
Observações: o catálogo em disco é a fonte de verdade; as skills embutidas são um complemento.
"""
from __future__ import annotations

from agent.skills.catalog.loader import (
    catalog_dir,
    default_catalog_dir,
    load_catalog,
    parse_frontmatter,
    parse_skill_markdown,
)

__all__ = [
    "catalog_dir",
    "default_catalog_dir",
    "load_catalog",
    "parse_frontmatter",
    "parse_skill_markdown",
]
