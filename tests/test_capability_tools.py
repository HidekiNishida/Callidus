"""
Arquivo: tests/test_capability_tools.py
Nome: test_capability_tools.py
Propósito: verificar as capacidades compostas determinísticas (capability_tools).
Responsabilidade: camada de testes — inspecionar subsistema, rastrear dependência,
analisar impacto, encontrar testes relacionados, preparar edição, validar alteração,
revisar diff, diagnosticar falha, recuperar operação.
Dependências: agent.tools.capability_tools, agent.persistence (database, models),
agent.services.project_service, agent.domain.schemas, pytest.
Observações: banco SQLite temporário por teste; arquivos temporários em tmp_path.
"""

from pathlib import Path

import pytest

from agent.domain.schemas import ProjectCreate
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.tools.capability_tools import (
    analyze_impact,
    diagnose_failure,
    find_related_tests,
    inspect_subsystem,
    prepare_edit,
    recover_operation,
    register_capability_tools,
    review_diff,
    trace_dependency,
    validate_change,
)


@pytest.fixture
def session(tmp_path: Path):
    settings = __import__("agent.config", fromlist=["Settings"]).Settings(data_dir=tmp_path)
    engine = init_db(settings=settings)
    factory = build_session_factory(engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def ctx(session, tmp_path: Path):
    """Contexto de ferramenta com sessão e projeto temporário."""
    from agent.tools.registry import ToolContext

    ps = ProjectService(session)
    project = ps.create_project(ProjectCreate(name="demo", root_path=str(tmp_path), description="test"))
    # Cria arquivos de exemplo no projeto.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert main() == 1\n", encoding="utf-8")
    session.commit()
    return ToolContext(session=session, project_root=str(tmp_path), task_id=project.id)


def test_register_capability_tools():
    """O registro de capacidades não levanta exceção."""
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    register_capability_tools(reg)
    # Apenas verifica que não levanta.


def test_inspect_subsystem(ctx):
    """inspect_subsystem devolve arquivos relacionados e componentes afetados."""
    result = inspect_subsystem(ctx, {"subsystem": "src/main.py", "objective": "inspecionar main", "limit": 5})
    assert result["subsystem"] == "src/main.py"
    assert "files" in result
    assert "summary" in result
    assert isinstance(result["files"], list)


def test_trace_dependency(ctx):
    """trace_dependency rastreia dependentes de um arquivo."""
    result = trace_dependency(ctx, {"path": "src/main.py", "direction": "dependents", "max_depth": 3})
    assert result["path"] == "src/main.py"
    assert result["direction"] == "dependents"
    assert "nodes" in result
    assert "impact" in result


def test_analyze_impact(ctx):
    """analyze_impact devolve componentes afetados, testes e risco."""
    result = analyze_impact(ctx, {"path": "src/main.py", "objective": "alterar função principal"})
    assert result["path"] == "src/main.py"
    assert "affected_components" in result
    assert "related_tests" in result
    assert "risk_score" in result
    assert "risk" in result
    assert result["risk"] in {"baixo", "medio", "alto"}


def test_find_related_tests(ctx):
    """find_related_tests encontra testes relacionados a um arquivo."""
    result = find_related_tests(ctx, {"path": "src/main.py", "objective": "main", "limit": 5})
    assert result["path"] == "src/main.py"
    assert "tests" in result
    assert isinstance(result["tests"], list)


def test_prepare_edit(ctx):
    """prepare_edit lê o arquivo, guarda o hash e devolve prontidão."""
    result = prepare_edit(ctx, {"path": "src/main.py", "objective": "alterar main"})
    assert result["ready"] is True
    assert result["path"] == "src/main.py"
    assert result["hash"]
    assert result["size"] > 0
    assert result["content"]
    assert "conflicts" in result


def test_prepare_edit_missing_file(ctx):
    """prepare_edit de arquivo inexistente devolve ready=False."""
    result = prepare_edit(ctx, {"path": "src/inexistente.py", "objective": "x"})
    assert result["ready"] is False
    assert "error" in result or "conflicts" in result


def test_validate_change(ctx):
    """validate_change valida sintaxe e deteta conflitos."""
    # Conteúdo válido.
    result = validate_change(
        ctx,
        {
            "path": "src/main.py",
            "content": "def main():\n    return 2\n",
            "expected_hash": "hash_invalido",
        },
    )
    assert "valid" in result
    assert "conflicts" in result
    assert "errors" in result


def test_validate_change_syntax_error(ctx):
    """validate_change deteta erro de sintaxe em Python."""
    result = validate_change(
        ctx,
        {
            "path": "src/main.py",
            "content": "def main(:\n    return 1\n",
        },
    )
    assert result["valid"] is False
    assert len(result["errors"]) > 0


def test_review_diff(ctx):
    """review_diff resume alterações de um diff."""
    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
 def main():
-    return 1
+    return 2
"""
    result = review_diff(ctx, {"diff": diff, "path": "src/main.py"})
    assert result["files_affected"] >= 1
    assert result["lines_added"] >= 1
    assert result["lines_removed"] >= 1
    assert result["risk"] in {"baixo", "medio", "alto"}


def test_diagnose_failure_syntax():
    """diagnose_failure classifica erro de sintaxe."""
    result = diagnose_failure(None, {"error": "SyntaxError: invalid syntax", "context": "em main.py"})
    assert result["category"] == "erro de código"
    assert result["recoverable"] is True


def test_diagnose_failure_timeout():
    """diagnose_failure classifica timeout."""
    result = diagnose_failure(None, {"error": "TimeoutError: operação expirou"})
    assert result["category"] == "timeout"


def test_recover_operation(session, ctx):
    """recover_operation restaura estado da tarefa ou sugere alternativa."""
    # Tarefa inexistente: devolve alternativa.
    import uuid

    result = recover_operation(
        ctx, {"task_id": str(uuid.uuid4()), "operation": "implement", "strategy": "reinspecionar"}
    )
    assert "recovered" in result
    assert "alternative" in result or "state" in result
