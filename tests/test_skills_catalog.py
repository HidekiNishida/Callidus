# tests/test_skills_catalog.py — Testes do catálogo de Skills em Markdown (fonte de verdade)
from pathlib import Path

import pytest

from agent.skills.catalog.loader import (
    catalog_dir,
    default_catalog_dir,
    load_catalog,
    parse_frontmatter,
    parse_skill_markdown,
)
from agent.skills.discovery import SkillRegistry


def test_parse_frontmatter_supports_scalars_and_lists():
    front, body = parse_frontmatter(
        "---\n"
        "id: minha_skill\n"
        "name: Minha Skill\n"
        "keywords:\n"
        "  - alpha\n"
        "  - beta\n"
        "tools: [file_read, file_write]\n"
        "---\n\n"
        "## Procedimentos operacionais\n"
        "1. Primeiro passo\n"
    )
    assert front["id"] == "minha_skill"
    assert front["keywords"] == ["alpha", "beta"]
    assert front["tools"] == ["file_read", "file_write"]
    assert "Procedimentos operacionais" in body


def test_parse_skill_markdown_extracts_all_contract_fields(tmp_path: Path):
    path = tmp_path / "minha-skill.md"
    path.write_text(
        "---\n"
        "id: minha_skill\n"
        "name: Minha Skill\n"
        "description: Uma competência de teste.\n"
        "version: 2.1.0\n"
        "required_tools:\n"
        "  - file_read\n"
        "  - pytest_run\n"
        "applies_to_kinds:\n"
        "  - MODEL_OPERATION\n"
        "keywords:\n"
        "  - testagem\n"
        "---\n\n"
        "## Critérios de ativação\n"
        "- Tarefas de teste\n\n"
        "## Quando não utilizar\n"
        "- Tarefas de leitura pura\n\n"
        "## Procedimentos operacionais\n"
        "1. Planeje\n"
        "2. Execute\n\n"
        "## Critérios de validação\n"
        "- Testes passando\n\n"
        "## Riscos\n"
        "- Regressão silenciosa\n",
        encoding="utf-8",
    )

    skill = parse_skill_markdown(path.read_text(encoding="utf-8"), source_path=path)

    assert skill.id == "minha_skill"
    assert skill.name == "Minha Skill"
    assert skill.version == "2.1.0"
    assert skill.description == "Uma competência de teste."
    assert skill.required_tools == ["file_read", "pytest_run"]
    assert skill.applies_to_kinds == ["MODEL_OPERATION"]
    assert skill.keywords == ["testagem"]
    assert skill.activation_criteria == ["Tarefas de teste"]
    assert skill.prohibited_criteria == ["Tarefas de leitura pura"]
    assert skill.procedures == ["Planeje", "Execute"]
    assert skill.validation_rules == ["Testes passando"]
    assert skill.risk_factors == ["Regressão silenciosa"]
    assert skill.is_valid()


def test_load_catalog_ignores_readme_and_invalid_files(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Não é uma skill\n", encoding="utf-8")
    (tmp_path / "boa.md").write_text(
        "---\nid: boa\nname: Boa\ndescription: Descrição válida.\n---\n\n"
        "## Procedimentos operacionais\n1. Fazer algo\n",
        encoding="utf-8",
    )
    (tmp_path / "quebrada.md").write_text("---\nid: \n---\n\ntexto\n", encoding="utf-8")

    skills = load_catalog(tmp_path)
    ids = [s.id for s in skills]
    assert "boa" in ids
    assert "quebrada" not in ids


def test_default_catalog_dir_points_to_repository_skills():
    directory = default_catalog_dir()
    assert directory is not None
    assert directory.name == "skills"
    assert (directory / "README.md").is_file()


def test_catalog_dir_prefers_project_skills(tmp_path: Path):
    project_skills = tmp_path / "skills"
    project_skills.mkdir()
    assert catalog_dir(tmp_path) == project_skills


def test_registry_loads_catalog_over_builtins():
    registry = SkillRegistry()
    skill = registry.get("debugging_root_cause")
    assert skill is not None
    # O catálogo do repositório sobrescreve a skill embutida (fonte de verdade).
    assert registry.source_of("debugging_root_cause") != "builtin"
    assert skill.keywords
    assert skill.risk_factors
    assert skill.required_tools


def test_registry_project_skills_override_repository(tmp_path: Path):
    project_skills = tmp_path / "skills"
    project_skills.mkdir()
    (project_skills / "custom.md").write_text(
        "---\nid: debugging_root_cause\nname: Debug do Projeto\n"
        "description: Competência específica do projeto.\n---\n\n"
        "## Procedimentos operacionais\n1. Olhar o log do projeto\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(project_root=tmp_path)
    skill = registry.get("debugging_root_cause")
    assert skill is not None
    assert skill.name == "Debug do Projeto"
    assert skill.procedures == ["Olhar o log do projeto"]


def test_registry_reports_invalid_skills(tmp_path: Path):
    project_skills = tmp_path / "skills"
    project_skills.mkdir()
    (project_skills / "invalida.md").write_text(
        "---\nid: invalida\nname: Invalida\ndescription: Sem procedimentos.\n---\n\ntexto\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(project_root=tmp_path)
    assert "invalida" in registry.list_invalid()
    assert registry.get("invalida") is None


@pytest.mark.parametrize(
    "objective,expected",
    [
        ("Corrigir o erro de KeyError no worker ao reiniciar", "debugging_root_cause"),
        ("Refatorar o módulo de rotas para reduzir acoplamento", "refactoring_clean_code"),
        ("Documentar a arquitetura do projeto no README", "technical_writing"),
        ("Criar testes automatizados e validar critérios de aceite", "testing_quality_assurance"),
        ("Implementar novo endpoint de exportação de métricas", "software_engineering"),
    ],
)
def test_selector_picks_expected_skill(objective: str, expected: str):
    from agent.skills.selector import SkillSelector

    selector = SkillSelector(SkillRegistry())
    matches = selector.select(objective, max_skills=2)
    assert matches, f"nenhuma skill selecionada para: {objective}"
    assert expected in {m.skill_id for m in matches}
