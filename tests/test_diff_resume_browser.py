"""
Arquivo: tests/test_diff_resume_browser.py
Nome: test_diff_resume_browser.py
Propósito: Verificar o diff unificado, o resumo de retomada e as ferramentas de navegador.
Responsabilidade: camada de testes — marcação de linhas do diff, retorno do diff na edição, brief de retomada, proteção de URL e ferramenta desligada.
Componentes: diff unificado, diff devolvido pela edição, brief de retomada, guarda de URL e navegador desativado por padrão.
Dependências: agent.tools.diffing, agent.orchestrator.resume, agent.tools.browser e agent.tools.registry.
Observações: banco temporário em tmp_path; nenhuma navegação real é feita.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.resume import build_resume_brief
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.tools.browser import guard_url, parse_search_html
from agent.tools.diffing import unified_diff_text
from agent.tools.registry import ToolContext, build_default_registry


def test_unified_diff_marks_added_and_removed_lines():
    """O diff unificado conta a linha adicionada e a removida e mostra os dois trechos."""
    diff = unified_diff_text("app.py", "a = 1\n", "a = 2\n")
    assert diff["added"] == 1
    assert diff["removed"] == 1
    assert "+a = 2" in diff["diff"]
    assert "-a = 1" in diff["diff"]


@pytest.mark.asyncio
async def test_edit_file_returns_diff(tmp_path: Path):
    """A edição de arquivo devolve o diff da mudança aplicada."""
    target = tmp_path / "app.py"
    target.write_text("valor = 1\n", encoding="utf-8")
    registry = build_default_registry()
    out = await registry.execute(
        "edit_file",
        ToolContext(project_root=str(tmp_path)),
        {"path": "app.py", "old_string": "valor = 1", "new_string": "valor = 2"},
    )
    assert out["success"] is True
    assert "+valor = 2" in out["diff"]


def test_resume_brief_says_what_stopped_and_corrects_instruction(tmp_path: Path):
    """O brief de retomada diz onde parou, o que já foi feito e corrige a instrução."""
    engine = init_db(settings=Settings(data_dir=tmp_path))
    session = build_session_factory(engine)()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Fazer", objective="Criar a tela", kind="objective"))
    done = tasks.create_task(
        project.id,
        TaskCreate(title="Criar arquivo", objective="escrever", parent_id=root.id, kind="operation"),
    )
    stopped = tasks.create_task(
        project.id,
        TaskCreate(title="Rodar testes", objective="pytest", parent_id=root.id, kind="operation"),
    )
    done.status = "COMPLETED"
    stopped.status = "BLOCKED"
    stopped.consolidated_result_json = {"result": {"error": "teste falhou"}}
    session.commit()
    brief = build_resume_brief(session, root)
    assert brief["stopped_at"] == "Rodar testes"
    assert "Criar arquivo" in brief["done"]
    assert "Rodar testes" in brief["missing"]
    assert "teste falhou" in brief["corrected_instruction"]
    assert "Criar a tela" in brief["corrected_instruction"]
    session.close()


def test_browser_guards_and_parses_results():
    """A guarda recusa URL de arquivo local e a leitura do HTML extrai título e endereço dos resultados."""
    with pytest.raises(ValueError):
        guard_url("file:///etc/passwd")
    assert guard_url("https://exemplo.dev").startswith("https://")
    html = '<a class="result__a" href="https://exemplo.dev">Guia <b>local</b></a>'
    hits = parse_search_html(html)
    assert hits[0]["title"] == "Guia local"
    assert hits[0]["url"] == "https://exemplo.dev"


@pytest.mark.asyncio
async def test_browser_tool_stays_off_until_enabled(tmp_path: Path):
    """A ferramenta de navegador recusa a navegação enquanto está desligada."""
    registry = build_default_registry()
    off = await registry.execute(
        "browser",
        ToolContext(project_root=str(tmp_path)),
        {"action": "navigate", "url": "https://exemplo.dev"},
    )
    assert off["success"] is False
    assert "desligado" in off["error"]
