# tests/test_skills_system.py — Testes do sistema de Skills (descoberta, validação, seleção sob demanda)
from pathlib import Path
import pytest

from agent.skills.builtins import get_builtin_skills
from agent.skills.discovery import SkillRegistry, get_skill_registry
from agent.skills.models import SkillSpec
from agent.skills.selector import SkillSelector


def test_builtin_skills_load_and_are_valid():
    skills = get_builtin_skills()
    assert len(skills) >= 6
    for s in skills:
        assert s.is_valid(), f"Skill {s.id} inválida: {s.validate()}"
        assert s.id
        assert s.name
        assert s.description
        assert len(s.procedures) > 0
        assert len(s.validation_rules) > 0


def test_registry_loads_builtins_and_handles_invalid_skills():
    registry = SkillRegistry()
    assert len(registry.list_all()) >= 6
    assert registry.get("software_engineering") is not None
    assert registry.get("debugging_root_cause") is not None

    # Registrar skill inválida deve levantar erro e ser registrada como inválida
    invalid_skill = SkillSpec(id="", name="", description="")
    with pytest.raises(ValueError):
        registry.register(invalid_skill)
    assert "" in registry.list_invalid()


def test_registry_discovers_skills_from_directory(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    custom_skill = skills_dir / "custom-optimization.md"
    custom_skill.write_text(
        "---\n"
        "id: performance_optimization\n"
        "name: Otimização de Performance\n"
        "description: Otimização de latência e consumo de memória.\n"
        "---\n\n"
        "## Procedimentos operacionais\n"
        "1. Realizar profiling do código antes de otimizar\n"
        "2. Identificar gargalos de CPU e memória\n\n"
        "## Critérios de validação\n"
        "- Redução comprovada do tempo de execução\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(project_root=tmp_path)
    found = registry.get("performance_optimization")
    assert found is not None
    assert found.name == "Otimização de Performance"
    assert len(found.procedures) == 2
    assert len(found.validation_rules) == 1


def test_skill_selector_matches_relevant_skills():
    registry = SkillRegistry()
    selector = SkillSelector(registry)

    # Tarefa de bugfix deve selecionar debugging_root_cause
    matches_bug = selector.select("Corrigir bug de timeout na chamada da api e resolver o erro")
    assert len(matches_bug) > 0
    top_skill = matches_bug[0]
    assert top_skill.skill_id == "debugging_root_cause"

    # Tarefa de documentação deve selecionar technical_writing
    matches_doc = selector.select("Atualizar a documentação técnica e o README do projeto")
    assert len(matches_doc) > 0
    assert any(m.skill_id == "technical_writing" for m in matches_doc)

    # Tarefa de teste deve selecionar testing_quality_assurance
    matches_qa = selector.select("Criar testes automatizados com pytest e validar critérios de aceite")
    assert len(matches_qa) > 0
    assert any(m.skill_id == "testing_quality_assurance" for m in matches_qa)


def test_skill_selector_renders_within_budget():
    registry = SkillRegistry()
    selector = SkillSelector(registry)
    matches = selector.select("Implementar nova rota de exportação no backend e criar testes")
    rendered = selector.render_selected_skills(matches, max_chars=1200)

    assert "## Competências e Procedimentos de Especialidade" in rendered
    assert len(rendered) <= 1300
    assert "Procedimentos operacionais" in rendered
